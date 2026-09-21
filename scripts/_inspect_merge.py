import json
from app.services import kb_service
p='reports/common_kb_deep_test_20260811_113653.json'
data=json.load(open(p,encoding='utf-8'))
for row in data['results']:
    if row['id'] not in {'C12','C14','C21'}: continue
    docs=[]
    for item in row['top_results']:
        docs.append({'question':item.get('title',''),'answer':item.get('content',''),'title':item.get('title',''),'_keyword_score':0,'_query_relevance_score':None})
    q=row['question']
    print('\n',row['id'],q)
    print('terms',kb_service.build_keyword_terms(q))
    print('anchors',kb_service.extract_query_anchor_terms(q),'stable',kb_service.has_stable_query_subject_anchor(q))
    print('subject',kb_service.extract_query_subject_evidence_bigrams(q))
    print('merge',kb_service.should_merge_keyword_fallback_for_results(q,docs))
    for d in docs[:4]:
        print('  ',d['question'][:60], 'qev',kb_service.score_query_question_text_evidence(q,d),'direct',kb_service.score_query_direct_text_evidence(q,d),'rel',kb_service.score_query_relevance(q,d))
