"""Regression cases from the saved timeline quality review."""
import unittest
from unittest.mock import patch
import time
import timeline as t


def article(html):
    parser = t.ArticleParser()
    parser.feed(html)
    return {"url": "https://example.org/history", "title": "歴史", "text": parser.text(), "passages": parser.passages(), "lead": ""}


class ContextTests(unittest.TestCase):
    def test_install_steps_and_versions_are_not_dates(self):
        self.assertIsNone(t.heading_year('4'))
        self.assertFalse(t.DATE_PATTERN.search('version 2.1.207'))
        self.assertTrue(t.DATE_PATTERN.search('It opened in 1685.'))
        source = article('<h3>4</h3><p>Claude Codeをインストールします。</p>')
        self.assertEqual(t.select_passages(source['passages'], t.parse_query('Claude Code')), [])

    def test_multiple_keywords_use_parent_headings(self):
        for topic, html in [('Claude Code','<h1>Claude Code</h1><h2>2025年</h2><p>The developer tool became generally available.</p>'), ('半導体 日本','<h1>日本の半導体産業の歴史</h1><h2>1980年</h2><p>半導体の生産額が世界最大になった。</p>')]:
            self.assertTrue(t.select_passages(article(html)['passages'], t.parse_query(topic)))

    def test_section_year_is_not_replaced_by_background_year(self):
        source = article('<h3>2008</h3><p>2006年に米国で誕生したTwitterの日本語版が開始された。</p>')
        event = {"year": 2006, "date": "2006年", "title": "Twitter日本語版の開始", "description": "Twitterの日本語版が開始された。", "quote": "2006年に米国で誕生したTwitterの日本語版が開始された。", "source_id": 1}
        self.assertIn('2008', source['text'])
        self.assertEqual(t.validate_events([event], [source], t.parse_query('インターネット')), [])
        correct = t.validate_events([event | {"year": 2008, "date": "2008年"}], [source], t.parse_query('インターネット'))
        self.assertEqual(correct[0]['year'], 2008)
        self.assertIn('2008', correct[0]['source']['context_heading'])

    def test_ambiguous_repeat_under_different_years_is_rejected(self):
        source = article('<h3>2006</h3><p>サービスを一般に公開しました。</p><h3>2008</h3><p>サービスを一般に公開しました。</p>')
        event = {"year": 2008, "date": "2008年", "title": "サービス公開", "description": "サービスを公開しました。", "quote": "サービスを一般に公開しました。", "source_id": 1}
        self.assertEqual(t.validate_events([event], [source], t.parse_query('サービス')), [])
        source['all_passages'] = source['passages']
        source['passages'] = source['passages'][:1]
        self.assertEqual(t.validate_events([event | {'year':2006}], [source], t.parse_query('サービス')), [])

    def test_heading_names_and_approximate_year_are_preserved(self):
        source = article('<h2>2025年 Claude Code一般公開</h2><p>開発者向けのツールを一般公開しました。</p>')
        event = {'year':2025,'date':'2025年','title':'Claude Code一般公開','description':'Claude Codeを一般公開しました。','quote':source['passages'][0]['text'],'source_id':1}
        self.assertEqual(len(t.validate_events([event], [source], t.parse_query('Claude Code'))),1)
        source = article('<h3>900年ごろ</h3><p>コーヒーについて記録された。</p>')
        event.update(year=900,date='900年',title='コーヒーの記録',description='コーヒーについて記録された。',quote=source['passages'][0]['text'])
        self.assertEqual(t.validate_events([event],[source],t.parse_query('コーヒー'))[0]['date'],'900年ごろ')
        self.assertIn('15世紀', article('<h3>15世紀</h3><p>コーヒーを飲む習慣が広まった。</p>')['text'])

    def test_acronym_must_not_match_letters_inside_unrelated_word(self):
        source=article('<h2>2025年 Claude Code</h2><p>Claude Code is generally available with negative test coverage.</p>')
        event={'year':2025,'date':'2025年','title':'Claude Code GA','description':'Claude Codeを一般公開しました。','quote':source['passages'][0]['text'],'source_id':1}
        self.assertEqual(t.validate_events([event],[source],t.parse_query('Claude Code')),[])

    def test_legend_cannot_become_unqualified_fact(self):
        source = article('<h2>1683年</h2><p>伝説によれば、ウィーンに最初のコーヒーハウスが開かれました。</p>')
        event = {"year": 1683, "date": "1683年", "title": "ウィーンの店", "description": "ウィーンに最初のコーヒーハウスが開かれました。", "quote": source['passages'][0]['text'], "source_id": 1}
        self.assertEqual(t.validate_events([event], [source], t.parse_query('コーヒー')), [])
        self.assertEqual(len(t.validate_events([event | {"description": "伝説では、ウィーンにコーヒーハウスが開かれたとされています。"}], [source], t.parse_query('コーヒー'))), 1)

    def test_neighbor_hedge_on_another_claim_does_not_drop_event(self):
        quote = '1554年、シェムジとヘケムが、コンスタンティノープルにそれぞれコーヒーハウスを開業しました。'
        source = article('<h2>コーヒーの歴史</h2><p>' + quote + '</p><p>この2店が世界最初のコーヒーハウスと言われています。</p>')
        self.assertIn('世界最初', t.quote_context(source, quote)['after'])
        event = {"year": 1554, "date": "1554年", "title": "コーヒーハウス開業", "description": "コンスタンティノープルにコーヒーハウスが開業した。", "quote": quote, "source_id": 1}
        self.assertEqual(len(t.validate_events([event], [source], t.parse_query('コーヒー'))), 1)
        self.assertEqual(t.validate_events([event | {"description": "コンスタンティノープルに世界最初のコーヒーハウスが開業した。"}], [source], t.parse_query('コーヒー')), [])
        hedged_year = article('<h2>コーヒーの歴史</h2><p>伝説では1554年のことと言われています。</p><p>' + quote + '</p>')
        self.assertEqual(t.validate_events([event], [hedged_year], t.parse_query('コーヒー')), [])

    def test_historical_name_is_not_treated_as_uncertain_claim(self):
        source=article('<h2>1958年</h2><p>初のインスタントラーメンを発売。それ以前は「中華そば」と言われていた。</p>')
        event={'year':1958,'date':'1958年','title':'インスタントラーメン発売','description':'インスタントラーメンを発売した。','source_id':1,'quote':source['passages'][0]['text']}
        self.assertEqual(len(t.validate_events([event],[source],t.parse_query('ラーメン'))),1)

    def test_exact_day_requires_actual_date_and_valid_calendar(self):
        quote = 'Claude Code is now generally available.'
        source = article('<h1>Introducing Claude 4</h1><p>May 22, 2025</p><p>'+quote+'</p>')
        source['lead'] = 'May 22, 2025'
        event = {"year": 2025, "date": "2025年5月22日", "title": "Claude Code一般公開", "description": "Claude Codeが一般公開された。", "quote": quote, "source_id": 1}
        valid = t.validate_events([event], [source], t.parse_query('Claude Code'))
        self.assertEqual(valid[0]['date'], '2025年5月22日')
        self.assertEqual(t.validate_events([event | {'date':'2025-05-22'}], [source], t.parse_query('Claude Code'))[0]['date'],'2025年5月22日')
        for value in ['2025年5月23日', '2025年2月30日']:
            valid = t.validate_events([event | {'date':value}], [source], t.parse_query('Claude Code'))
            self.assertEqual(valid[0]['date'], '2025年')

    def test_long_exact_quote_is_checked_before_bounded_excerpt(self):
        text='Claude Code is now generally available. '+('Developers can use this tool in their terminal. '*6)
        source=article('<h2>2025年</h2><p>'+text+'</p>')
        event={'year':2025,'date':'2025年','title':'Claude Code一般公開','description':'Claude Codeを一般公開した。','source_id':1,'quote':text.strip()}
        valid=t.validate_events([event],[source],t.parse_query('Claude Code'))
        self.assertEqual(len(valid),1)
        self.assertLessEqual(len(valid[0]['quote']),160)
        self.assertIn(valid[0]['quote'],source['text'])
        self.assertIn(text.strip(),valid[0]['_context']['passage'])
        self.assertEqual(t.validate_events([event|{'quote':text.strip()+' Invented claim.'}],[source],t.parse_query('Claude Code')),[])

    def test_balanced_selection_keeps_late_milestone_after_large_beginning(self):
        html = ''.join(f'<h3>{1800+i}</h3><p>{1800+i}年にコーヒーの店が開店。'+('説明。'*30)+'</p>' for i in range(30))
        html += '<h3>1969</h3><p>1969年にミルク入り缶コーヒーを発売しました。</p>'
        html += '<h3>1899</h3><p>1899年にコーヒーの店が開店。'+('説明。'*30)+'</p>'
        source = article(html)
        self.assertGreater(source['text'].find('1969'), 3000)
        passages = t.select_passages(source['passages'], t.parse_query('コーヒー'), 1000)
        self.assertTrue(any('1969' in p['text'] for p in passages))
        self.assertTrue(any('1800' in p['text'] for p in passages))
        self.assertLessEqual(sum(len(p['text'])+len(p['heading']) for p in passages), 1000)

    def test_selection_spreads_remaining_budget_across_eras(self):
        html = ''.join(f'<h3>{1800+i}</h3><p>コーヒーを発売しました。'+('詳しい説明。'*12)+'</p>' for i in range(100))
        selected=t.select_passages(article(html)['passages'],t.parse_query('コーヒー'),1400)
        counts=[0]*5
        for p in selected:
            counts[(int(p['date_heading'])-1800)//20]+=1
        self.assertTrue(all(n>=2 for n in counts),counts)

    def test_excerpt_selection_respects_requested_period(self):
        source=article('<h2>1967</h2><p>インターネットの研究開始。</p><h2>1983</h2><p>インターネットの方式を移行。</p><h2>2008</h2><p>インターネットのサービス開始。</p>')
        selected=t.select_passages(source['passages'],t.Query('', 'インターネット', 1980, 1990))
        self.assertEqual([p['date_heading'] for p in selected],['1983'])
        ancient=article('<p>紀元前500年、ローマで制度が始まった。</p>')
        self.assertTrue(t.select_passages(ancient['passages'],t.Query('', 'ローマ', -600, -400)))

    def test_verifier_sees_context_and_theme_does_not_expand(self):
        source = article('<h3>2008</h3><p>Twitterの日本語版サービスを開始しました。</p>')
        event = {"year": 2008, "date": "2008年", "title": "Twitter日本語版の開始", "description": "Twitterの日本語版サービスが開始された。", "quote": source['passages'][0]['text'], "source_id": 1}
        with patch.object(t, 'search', return_value=[{}]), patch.object(t.WebReader, 'fetch', return_value=source), patch.object(t, 'model_json', side_effect=[{'theme':'インターネットと関連サービス全部','events':[event]},{'supported':[0]}]) as model:
            result = t.build_timeline(t.parse_query('インターネット'), lambda _:None)
        self.assertIn('2008', model.call_args_list[1].args[1])
        self.assertIn('context', model.call_args_list[1].args[1])
        self.assertEqual(result['theme'], 'インターネット')
        self.assertNotIn('_context', result['events'][0])

    def test_search_prefers_institutional_and_encyclopedia_sources_without_excluding_blogs(self):
        hosts=['example.hatenablog.com','example.com','ja.wikipedia.org','www.ndl.go.jp','www.raumen-museum.jp']
        results=[{'title':'ラーメン 歴史','content':'ラーメンの歴史','url':f'https://{host}/ramen'} for host in hosts]
        with patch.object(t,'json_request',return_value={'results':results}):
            actual=[r['url'] for r in t.search(t.parse_query('ラーメン'))]
        self.assertEqual(actual,['https://www.ndl.go.jp/ramen','https://www.raumen-museum.jp/ramen','https://ja.wikipedia.org/ramen','https://example.com/ramen','https://example.hatenablog.com/ramen'])
        with patch.object(t,'json_request',return_value={'results':results[:1]}):
            self.assertEqual(len(t.search(t.parse_query('ラーメン'))),1)
        self.assertEqual(t.source_tier('https://ramen-museum.hatenablog.com/x'),-6)
        self.assertEqual(t.source_tier('https://www.wien.gv.at/kaffee'),6)

    def test_crosscheck_authority_shares_source_tier(self):
        results=[{'title':'Vienna coffee history','url':f'https://{host}/kaffee'} for host in ['blog.example.hatenablog.com','example.com','www.wien.gv.at']]
        results.append({'title':'Vienna official coffee history','url':'https://example.org/kaffee'})
        actual=[r['url'] for r in sorted(results,key=t.authority,reverse=True)]
        self.assertEqual(actual,['https://www.wien.gv.at/kaffee','https://example.org/kaffee','https://example.com/kaffee','https://blog.example.hatenablog.com/kaffee'])
        self.assertEqual(t.authority({'url':'http://[::1'}),-100)

    def test_crosscheck_uses_specific_subject_and_skips_duplicates(self):
        source=article('<h2>1685</h2><p>Vienna opened its first documented coffee house in 1685.</p>')
        source['url']='https://example.org/other'
        results=[{'title':'Unrelated historical museum','content':'History museum','url':'https://example.org/unrelated'}, {'title':'Vienna official history','content':'First coffee house','url':source['url']}, {'title':'Vienna old source','content':'First coffee house','url':'https://example.org/old'}]
        event={'title':'ウィーン初の店','description':'最初の店を開いた。','_check_query':'Vienna first coffeehouse history'}
        with patch.object(t,'json_request',return_value={'results':results}) as request, patch.object(t.WebReader,'fetch',return_value=source) as fetch:
            actual=t.crosscheck_sources([event,event],[{'url':'https://example.org/old','passages':[]}],t.parse_query('コーヒー'),time.monotonic()+100)
        self.assertEqual(len(actual),1)
        self.assertEqual(request.call_count,1)
        self.assertEqual(fetch.call_count,1)
        self.assertIn('1685',actual[0]['passages'][0]['text'])
        with patch.object(t,'json_request') as request:
            self.assertEqual(t.crosscheck_sources([event],[source],t.parse_query('コーヒー'),time.monotonic()+40),[])
            request.assert_not_called()

    def test_cautionary_and_conflicting_passages_survive_excerpt_budget(self):
        html='<h1>Vienna coffee houses</h1><h2>1683</h2><p>Legend says the first Vienna coffee house opened in 1683. '+('A historical detail. '*15)+'</p>'
        html+='<p>However, the first documented Vienna coffee house had a different owner.</p>'
        html+=''.join(f'<h2>{1800+i}</h2><p>Vienna opened a new coffee house in {1800+i}. '+('Additional details. '*8)+'</p>' for i in range(10))
        selected=t.select_passages(article(html)['passages'],t.parse_query('Vienna'),1100)
        self.assertTrue(any('Legend' in p['text'] for p in selected))
        self.assertTrue(any('However' in p['text'] for p in selected))

    def test_unknown_event_time_is_not_inferred_from_section_year(self):
        source=article('<h2>1641年</h2><p>日本に伝わった年はいつ頃かは不明ですが、長崎の商館経由とされています。</p>')
        event={'year':1641,'date':'1641年','title':'コーヒーの伝来','description':'商館経由で伝わったとされています。','source_id':1,'quote':source['passages'][0]['text']}
        self.assertEqual(t.validate_events([event],[source],t.parse_query('コーヒー')),[])
        source=article('<h2>1958年</h2><p>起源の時期は不明ですが、1958年に新方式の製品を発売しました。</p>')
        event.update(year=1958,date='1958年',title='新方式の発売',description='1958年に新方式の製品を発売した。',quote=source['passages'][0]['text'])
        self.assertEqual(len(t.validate_events([event],[source],t.parse_query('製品'))),1)

    def test_duplicated_year_heading_is_removed_without_inventing_quote(self):
        source=article('<h2>1969年</h2><p>ミルク入り缶コーヒーを開発・生産しました。</p>')
        event={'year':1969,'date':'1969年','title':'缶コーヒーの誕生','description':'ミルク入り缶コーヒーを開発した。','source_id':1,'quote':'1969年、ミルク入り缶コーヒーを開発・生産しました。'}
        result=t.validate_events([event],[source],t.parse_query('コーヒー'))
        self.assertEqual(result[0]['quote'],'ミルク入り缶コーヒーを開発・生産しました。')
        self.assertEqual(t.validate_events([event|{'quote':'1968年、ミルク入り缶コーヒーを開発・生産しました。'}],[source],t.parse_query('コーヒー')),[])
        self.assertEqual(t.validate_events([event|{'quote':'1969年、ミルク入り缶コーヒーを初めて開発・生産しました。'}],[source],t.parse_query('コーヒー')),[])

    def test_comparison_legend_with_same_year_and_named_subject_is_visible(self):
        event={'year':1683,'date':'1683年','title':'都市初の店','description':'都市最初の店を開店した。','_check_query':'Franz Georg Kolschitzky Vienna first coffee house'}
        comparison={'source':'City history','url':'https://example.org/history','heading':'1683 Vienna','text':'Legend has it that Georg Franz Kolschitzky was the first to open a coffee house.'}
        result=t.legend_conflicts([event],[comparison])
        self.assertIn(0,result)
        self.assertEqual(result[0]['sources'][0]['url'],comparison['url'])
        self.assertEqual(t.legend_conflicts([event|{'year':1690}],[comparison]),{})
        self.assertEqual(t.legend_conflicts([event|{'_check_query':'Another Person Othercity first shop'}],[comparison]),{})
        self.assertEqual(t.legend_conflicts([event|{'description':'伝説では、最初の店を開店したとされる。'}],[comparison]),{})
        for text in ['Archival records establish that Georg Franz Kolschitzky opened the first coffee house in 1683; this is not a legend.', 'Georg Franz Kolschitzky opened the first coffee house in 1683. A local legend says a different shop was founded in 1800.', 'Legend says Georg Franz Kolschitzky opened a different shop in 1800.']:
            self.assertEqual(t.legend_conflicts([event],[comparison|{'text':text}]),{})

    def test_industrial_scores_do_not_exhaust_latest_era_reservation(self):
        html = '<h1>コーヒーの歴史</h1>' + ''.join(f'<h2>{year}</h2><p>コーヒーの製造方式を発明しました。'+('説明。'*34)+'</p>' for year in range(1800,1830))
        html += '<h2>1969</h2><p>ミルク入り缶コーヒーを発売しました。</p>'
        selected=t.select_passages(article(html)['passages'],t.parse_query('コーヒー'),1000)
        self.assertTrue(any('1969' in p['date_heading'] for p in selected))

    def test_following_counterevidence_is_kept_without_special_keywords(self):
        context = {'passage':'ウィーンに最初のコーヒーハウスが開かれました。', 'after':'この記録は後世の創作であり、当時の史料には記載がない。'}
        self.assertEqual(t.verification_context(context)['after'], context['after'])

    def test_model_calls_use_separate_generation_and_verification_models(self):
        with patch.object(t, 'json_request', return_value={'message': {'content':'{}'}}) as request:
            t.model_json('system', 'input', time.monotonic()+60, t.EVENT_SCHEMA)
            t.model_json('system', 'input', time.monotonic()+60, t.VERIFY_SCHEMA)
        self.assertEqual(request.call_args_list[0].args[1]['model'], t.MODEL)
        self.assertEqual(request.call_args_list[1].args[1]['model'], t.VERIFY_MODEL)

    def test_conflicting_rejection_keeps_supplement_links_without_raw_pages(self):
        source=article('<h3>1683</h3><p>ウィーンで最初のコーヒーハウスを開いた。</p>')
        supplement=article('<h3>1685</h3><p>史料で確認された最初の店を開いた。</p>')
        supplement['url']='https://example.org/verified'
        event={'year':1683,'date':'1683年','title':'ウィーン初の店','description':'最初のコーヒーハウスを開いた。','source_id':1,'quote':source['passages'][0]['text'],'check_query':'Vienna first coffeehouse'}
        with patch.object(t,'search',return_value=[{}]), patch.object(t.WebReader,'fetch',return_value=source), patch.object(t,'crosscheck_sources',return_value=[supplement]), patch.object(t,'model_json',side_effect=[{'theme':'コーヒー','events':[event]},{'supported':[],'rejected':[{'id':0,'reason':'伝説と史料に矛盾がある。'}]}]) as model:
            result=t.build_timeline(t.parse_query('コーヒー'),lambda _:None)
        self.assertEqual(result['events'],[])
        self.assertIn('1685',model.call_args_list[1].args[1])
        self.assertEqual(result['review_notes'][0]['sources'][0]['url'],supplement['url'])
        self.assertNotIn('text',result['review_notes'][0]['sources'][0])


if __name__ == '__main__':
    unittest.main()
