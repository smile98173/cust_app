<?php
/**
 * Web API 串接範例
 *
 * 正式 Web API 現在由本系統保存 ai_state 與 chat_logs。
 * Web server 只需要帶：
 * 1. user_id：會員編號或訪客流水號
 * 2. is_logged_in：登入會員狀態
 * 3. company_code：系統台代碼
 * 4. msg：使用者本輪輸入
 *
 * API 回覆的 msg 就是要顯示給使用者的 AI 回覆。
 * 若 msg 含網址，後端會直接回傳 <a> 標籤。
 */

session_start();

$apiBaseUrl = getenv('CUST_APP_API_BASE_URL') ?: 'https://aiia.topmso.com.tw:8000';
$apiAuthName = getenv('API_AUTH_NAME') ?: '';
$apiAuthPassword = getenv('API_AUTH_PASSWORD') ?: '';
$tokenEndpoint = rtrim($apiBaseUrl, '/') . '/api/auth/token';
$endpoint = rtrim($apiBaseUrl, '/') . '/api/v1/chat';

$companyCode = $_SESSION['company_code'] ?? 'tdtv';
$isLoggedIn = !empty($_SESSION['is_logged_in']);

if (!isset($_SESSION['web_user_id'])) {
    // 登入會員時，這裡請放會員編號；訪客時，這裡放訪客流水號。
    $_SESSION['web_user_id'] = $isLoggedIn
        ? ($_SESSION['login_user_id'] ?? '')
        : 'guest_' . bin2hex(random_bytes(8));
}

if (!isset($_SESSION['display_history'])) {
    $_SESSION['display_history'] = [];
}

function fetchApiToken(string $tokenEndpoint, string $name, string $password): string
{
    if ($name === '' || $password === '') {
        return '';
    }

    $payload = [
        'name' => $name,
        'password' => $password,
    ];

    $ch = curl_init($tokenEndpoint);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
        ],
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_TIMEOUT => 20,
    ]);

    $rawBody = curl_exec($ch);
    $statusCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    $data = json_decode($rawBody ?: '', true);
    if ($statusCode >= 200 && $statusCode < 300 && is_array($data)) {
        return (string)($data['access_token'] ?? '');
    }

    return '';
}

function getApiToken(string $tokenEndpoint, string $apiAuthName, string $apiAuthPassword): string
{
    $now = time();
    $cachedToken = $_SESSION['api_access_token'] ?? '';
    $expiresAt = (int)($_SESSION['api_access_token_expires_at'] ?? 0);

    if ($cachedToken !== '' && $expiresAt > $now + 60) {
        return $cachedToken;
    }

    $token = fetchApiToken($tokenEndpoint, $apiAuthName, $apiAuthPassword);
    if ($token !== '') {
        $_SESSION['api_access_token'] = $token;
        $_SESSION['api_access_token_expires_at'] = $now + 86400;
    }

    return $token;
}

function callAiChatApi(
    string $endpoint,
    array $payload,
    string $tokenEndpoint,
    string $apiAuthName,
    string $apiAuthPassword
): array
{
    $apiToken = getApiToken($tokenEndpoint, $apiAuthName, $apiAuthPassword);

    $headers = [
        'Content-Type: application/json',
    ];
    if ($apiToken !== '') {
        $headers[] = 'X-API-Token: ' . $apiToken;
    }

    $ch = curl_init($endpoint);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_TIMEOUT => 60,
    ]);

    $rawBody = curl_exec($ch);
    $curlError = curl_error($ch);
    $statusCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($rawBody === false) {
        return [
            'status' => 'error',
            'message' => 'API 連線失敗：' . $curlError,
        ];
    }

    $data = json_decode($rawBody, true);
    if (!is_array($data)) {
        return [
            'status' => 'error',
            'message' => 'API 回傳不是有效 JSON',
            'http_status' => $statusCode,
            'raw_body' => $rawBody,
        ];
    }

    if ($statusCode < 200 || $statusCode >= 300) {
        return [
            'status' => 'error',
            'message' => $data['detail'] ?? 'API 回傳錯誤',
            'http_status' => $statusCode,
            'raw_body' => $data,
        ];
    }

    return $data;
}

function renderChatMessage(string $role, string $content): string
{
    if ($role === 'assistant') {
        return nl2br(strip_tags($content, '<a>'));
    }

    return nl2br(htmlspecialchars($content, ENT_QUOTES, 'UTF-8'));
}

function appendDisplayHistory(string $role, string $content): void
{
    $_SESSION['display_history'][] = [
        'role' => $role,
        'content' => $content,
    ];

    if (count($_SESSION['display_history']) > 20) {
        $_SESSION['display_history'] = array_slice($_SESSION['display_history'], -20);
    }
}

$errorMessage = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $message = trim($_POST['message'] ?? '');

    if ($message !== '') {
        $payload = [
            'request_id' => 'req_' . date('YmdHis') . '_' . bin2hex(random_bytes(4)),
            'user_id' => $_SESSION['web_user_id'],
            'is_logged_in' => $isLoggedIn,
            'company_code' => $companyCode,
            'msg' => $message,
            'metadata' => [
                'page' => 'customer-service',
            ],
        ];

        $response = callAiChatApi(
            $endpoint,
            $payload,
            $tokenEndpoint,
            $apiAuthName,
            $apiAuthPassword
        );

        if (($response['status'] ?? '') === 'success') {
            $replyText = $response['msg'] ?? '';

            appendDisplayHistory('user', $message);
            appendDisplayHistory('assistant', $replyText);

            if (!empty($response['actions'])) {
                $_SESSION['last_actions'] = $response['actions'];
            }
        } else {
            $errorMessage = $response['message'] ?? 'API 呼叫失敗';
        }
    }
}
?>
<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <title>AI 客服 Web API PHP 範例</title>
    <style>
        body {
            font-family: Arial, "Microsoft JhengHei", sans-serif;
            margin: 32px;
            line-height: 1.6;
        }
        .chat {
            max-width: 880px;
        }
        .message {
            padding: 12px 16px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            white-space: pre-wrap;
        }
        .user {
            background: #eef6ff;
        }
        .assistant {
            background: #f7f7f7;
        }
        textarea {
            width: 100%;
            min-height: 90px;
        }
        button {
            padding: 10px 18px;
            margin-top: 8px;
        }
        .error {
            color: #b00020;
        }
        .meta {
            color: #666;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <main class="chat">
        <h1>AI 客服 Web API PHP 範例</h1>

        <p class="meta">
            API Endpoint: <?php echo htmlspecialchars($endpoint, ENT_QUOTES, 'UTF-8'); ?><br>
            User ID: <?php echo htmlspecialchars($_SESSION['web_user_id'], ENT_QUOTES, 'UTF-8'); ?><br>
            Is Logged In: <?php echo $isLoggedIn ? 'true' : 'false'; ?><br>
            Company Code: <?php echo htmlspecialchars($companyCode, ENT_QUOTES, 'UTF-8'); ?>
        </p>

        <?php if ($errorMessage): ?>
            <p class="error"><?php echo htmlspecialchars($errorMessage, ENT_QUOTES, 'UTF-8'); ?></p>
        <?php endif; ?>

        <?php foreach ($_SESSION['display_history'] as $item): ?>
            <?php $role = $item['role'] === 'user' ? 'user' : 'assistant'; ?>
            <div class="message <?php echo $role; ?>">
                <strong><?php echo $role === 'user' ? '使用者' : 'AI 客服'; ?></strong><br>
                <?php echo renderChatMessage($role, $item['content']); ?>
            </div>
        <?php endforeach; ?>

        <form method="post">
            <label for="message">輸入訊息</label><br>
            <textarea id="message" name="message" placeholder="例如：優惠套餐有哪些?"></textarea><br>
            <button type="submit">送出</button>
        </form>

        <?php if (!empty($_SESSION['last_actions'])): ?>
            <h2>Actions</h2>
            <pre><?php echo htmlspecialchars(json_encode($_SESSION['last_actions'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), ENT_QUOTES, 'UTF-8'); ?></pre>
        <?php endif; ?>
    </main>
</body>
</html>
