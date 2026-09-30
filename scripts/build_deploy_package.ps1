$ErrorActionPreference = 'Stop'

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
$releaseRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path $projectRoot -Parent) 'cust_app_releases'))
$projectPrefix = $projectRoot + [IO.Path]::DirectorySeparatorChar
if ($releaseRoot.Equals($projectRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $releaseRoot.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release output must be outside cust_app.'
}

$appRoot = Join-Path $projectRoot 'app'
$sources = @(Get-ChildItem -LiteralPath $appRoot -Recurse -File -Filter '*.py' |
    Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) })
foreach ($relativePath in @('requirements.txt', '.streamlit/config.toml')) {
    $sources += Get-Item -LiteralPath (Join-Path $projectRoot $relativePath)
}
if ($sources.Count -lt 3) {
    throw 'Required application files were not found.'
}
$sources = @($sources | Sort-Object FullName -Unique)

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
$archivePath = Join-Path $releaseRoot "cust_app_$($stamp)_$($suffix).zip"
$partialPath = "$archivePath.partial"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = $null
try {
    $archive = [IO.Compression.ZipFile]::Open($partialPath, [IO.Compression.ZipArchiveMode]::Create)
    $manifest = @(
        'Source: local working files (including uncommitted changes)'
        "Created: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
        'Scope: app Python code, Streamlit config, requirements.txt'
        'Excluded: env files, runtime data, databases, knowledge indexes, logs, feedback, tests, reports'
        ''
        'SHA256  Path'
    )

    foreach ($source in $sources) {
        $fullPath = [IO.Path]::GetFullPath($source.FullName)
        if (-not $fullPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Source file is outside cust_app: $fullPath"
        }
        $relativePath = $fullPath.Substring($projectPrefix.Length).Replace('\', '/')
        $entry = $archive.CreateEntry("cust_app/$relativePath", [IO.Compression.CompressionLevel]::Optimal)
        $inputStream = [IO.File]::OpenRead($fullPath)
        $entryStream = $entry.Open()
        try {
            $inputStream.CopyTo($entryStream)
        }
        finally {
            $entryStream.Dispose()
            $inputStream.Dispose()
        }
        $hashStream = [IO.File]::OpenRead($fullPath)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try {
            $hashBytes = $sha256.ComputeHash($hashStream)
        }
        finally {
            $sha256.Dispose()
            $hashStream.Dispose()
        }
        $hash = [BitConverter]::ToString($hashBytes).Replace('-', '').ToLowerInvariant()
        $manifest += "$hash  $relativePath"
    }

    $manifestEntry = $archive.CreateEntry('PACKAGE_MANIFEST.txt')
    $writer = [IO.StreamWriter]::new($manifestEntry.Open(), [Text.UTF8Encoding]::new($false))
    try {
        foreach ($line in $manifest) { $writer.WriteLine($line) }
    }
    finally {
        $writer.Dispose()
    }
    $archive.Dispose()
    $archive = $null
    Move-Item -LiteralPath $partialPath -Destination $archivePath
    Write-Host "Created: $archivePath"
    Write-Host "Packaged $($sources.Count) files. Review PACKAGE_MANIFEST.txt before deployment."
    Write-Host 'No files were uploaded or changed on the production server.'
}
catch {
    if ($null -ne $archive) { $archive.Dispose() }
    if (Test-Path -LiteralPath $partialPath) { Remove-Item -LiteralPath $partialPath -Force }
    throw
}
