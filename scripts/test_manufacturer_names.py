import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import match_manufacturer_names as matcher


def model(name='Ｌモンキーターン５ＣＥ', maker='山佐株式会社', kind='pachislot'):
    return {'id': 'test', 'name': name, 'reading': name, 'modelName': name,
            'manufacturer': maker, 'kind': kind, 'aliases': [], 'nameOrigin': 'notice'}


def product(name='スマスロモンキーターンⅤ', url='https://yamasa-next.co.jp/slot/monkey/', models=None):
    return {'name': name, 'url': url, 'modelNames': models or [], 'evidenceUrl': url}


def source(products, status='fresh'):
    return {'yamasa': {'products': products, 'status': status, 'fetchedAt': '2026-10-27T00:00:00Z'}}


class ManufacturerTests(unittest.TestCase):
    def test_sammy_json_keeps_actual_maker_and_kind_and_skips_unknown_maker(self):
        data = json.dumps({'products': [
            {'title': 'スマスロ 新作シリーズ2', 'maker': 'ロデオ', 'url': '/japanese/product/pachislot/new/'},
            {'title': '旧機種', 'maker': '', 'url': '/legacy/'},
        ]})
        rows = matcher.parse_sammy(data, 'https://new.sammy.co.jp/assets/js/slot.json', 'pachislot')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['makerKeys'], ['ロデオ'])
        self.assertEqual(len(matcher.candidate_matches(model('L新作シリーズ2XX', '株式会社ロデオ'), rows, 'sammy')), 1)
        self.assertEqual(matcher.candidate_matches(model('L新作シリーズ2XX', '株式会社銀座'), rows, 'sammy'), [])

    def test_sammy_pachinko_does_not_mix_prefix_or_numeric_specs(self):
        row = product('e北斗の拳激闘', 'https://new.sammy.co.jp/japanese/product/pachinko/new/')
        row.update(kind='pachinko', makerKeys=['銀座'])
        self.assertEqual(len(matcher.candidate_matches(model('e北斗の拳激闘GRED', '株式会社銀座', 'pachinko'), [row], 'sammy')), 1)
        self.assertEqual(matcher.candidate_matches(model('P北斗の拳激闘GRED', '株式会社銀座', 'pachinko'), [row], 'sammy'), [])
        row['name'] = 'e北斗の拳激闘119'
        self.assertEqual(matcher.candidate_matches(model('e北斗の拳激闘199GRED', '株式会社銀座', 'pachinko'), [row], 'sammy'), [])

    def test_regular_slot_never_takes_a_smart_slot_title(self):
        row = product('スマスロ新作シリーズ2', 'https://new.sammy.co.jp/product/new/')
        row.update(kind='pachislot', makerKeys=['サミー'])
        self.assertFalse(matcher.group_title_match(model('S新作シリーズ2XX', 'サミー株式会社'), row))

    def test_bellco_logo_identifies_manufacturer_instead_of_distributor(self):
        html = '<li class="c-archive03__item"><div class="is-name">L新作シリーズ2</div><div class="is-logo"><img alt="yama"></div><a href="/products/slot/new/">詳細</a></li>'
        rows = matcher.parse_bellco(html, 'https://www.s-bellco.co.jp/products/slot/')
        self.assertEqual(rows[0]['makerKeys'], ['ヤーマ'])
        self.assertEqual(len(matcher.candidate_matches(model('L新作シリーズ2XX', '株式会社ヤーマ'), rows, 'bellco')), 1)
        self.assertEqual(matcher.candidate_matches(model('L新作シリーズ2XX', 'ベルコ株式会社'), rows, 'bellco'), [])

    def test_bad_new_source_schema_is_rejected(self):
        with self.assertRaises(ValueError):
            matcher.parse_sammy('{"products":[]}', 'https://new.sammy.co.jp/assets/js/slot.json', 'pachislot')
        with self.assertRaises(ValueError):
            matcher.parse_bellco('<h1>アクセス制限</h1>', 'https://www.s-bellco.co.jp/products/slot/')

    def test_archive_removal_keeps_last_verified_name_after_notice_rebuild(self):
        row = model()
        row['manufacturerMatch'] = {'source': 'yamasa', 'name': 'スマスロモンキーターンⅤ', 'productUrl': 'https://yamasa-next.co.jp/slot/monkey/'}
        result, report = matcher.enrich({'machines': [row]}, source([]))
        self.assertEqual(result['machines'][0]['name'], 'スマスロモンキーターンⅤ')
        self.assertTrue(result['machines'][0]['manufacturerMatch']['stale'])
        self.assertEqual(report['counts']['matched'], 0)
        self.assertEqual(report['counts']['pending'], 1)

    def test_exact_model_pair_joins_only_same_official_product_slug(self):
        products = '<a class="slot-link_arealink" href="/slot/test/">新しい商品名</a>'
        notices = '<a class="slot-kentei-link" href="/slot-kentei/test/"><h2 class="slot-kentei-link_title">S試験KK</h2></a>'
        result = matcher.parse_kitadenshi(products, notices)
        self.assertEqual(result[0]['name'], '新しい商品名')
        self.assertEqual(result[0]['modelNames'], ['S試験KK'])
        self.assertEqual(result[0]['url'], 'https://www.kitadenshi.co.jp/slot/test/')
        with self.assertRaises(ValueError):
            matcher.parse_kitadenshi(products, notices.replace('/test/', '/other/'))

    def test_new_yamasa_product_is_discovered_without_a_title_dictionary(self):
        html = '<li class="machine"><p class="name">スマスロ新作シリーズ2</p><a class="site" href="/slot/new/">製品</a></li><a class="next page-numbers" href="/slots?paged=2">次へ</a>'
        rows, next_url = matcher.parse_yamasa(html, 'https://yamasa-next.co.jp/slots')
        self.assertEqual(rows[0]['name'], 'スマスロ新作シリーズ2')
        self.assertEqual(next_url, 'https://yamasa-next.co.jp/slots?paged=2')
        self.assertEqual(len(matcher.candidate_matches(model('Ｌ新作シリーズ２ＡＺ'), rows, 'yamasa')), 1)

    def test_external_pagination_is_rejected(self):
        html = '<li class="machine"><p class="name">新作</p><a class="site" href="/slot/new/">製品</a></li><a class="next page-numbers" href="https://example.com/slots?paged=2">次へ</a>'
        with self.assertRaises(ValueError):
            matcher.parse_yamasa(html, 'https://yamasa-next.co.jp/slots')

    def test_homepage_redirect_cannot_be_mistaken_for_a_product_list(self):
        with self.assertRaises(ValueError):
            matcher.parse_yamasa('<h1>公式トップページ</h1>', 'https://yamasa-next.co.jp/slots')

    def test_legacy_external_product_link_uses_official_index_as_evidence(self):
        html = '<li class="machine"><p class="name">スマスロ試験シリーズ</p><a class="site" href="http://legacy.example/">製品</a></li>'
        rows, _ = matcher.parse_yamasa(html, 'https://yamasa-next.co.jp/slots?paged=2')
        self.assertEqual(rows[0]['url'], 'https://yamasa-next.co.jp/slots?paged=2')

    def test_bt_label_requires_bt_model_prefix(self):
        self.assertTrue(matcher.compatible_title('LBケロット5ND05H', 'スマスロケロット5BT'))
        self.assertFalse(matcher.compatible_title('Lケロット5ND05H', 'スマスロケロット5BT'))

    def test_roman_series_number_and_examination_suffix(self):
        self.assertTrue(matcher.compatible_title('Ｌモンキーターン５ＣＥ', 'スマスロモンキーターンⅤ'))
        self.assertTrue(matcher.compatible_title('ＬモンキーターンＲＥＤＳＣ０４Ｈ', 'スマスロモンキーターンRED'))
        self.assertFalse(matcher.compatible_title('ＬモンキーターンＲＥＤＳＣ０４Ｈ', 'スマスロモンキーターンⅤ'))

    def test_different_series_and_30_phi_variants_are_not_removed_as_codes(self):
        self.assertFalse(matcher.compatible_title('Lテストシリーズ3AA', 'スマスロテストシリーズ2'))
        self.assertFalse(matcher.compatible_title('SテストシリーズAB-30', 'パチスロテストシリーズ'))
        self.assertFalse(matcher.compatible_title('Lテストシリーズ2AB', 'パチスロテストシリーズ'))
        self.assertFalse(matcher.compatible_title('SニューパルサーSP3CC', 'ニューパルサー'))

    def test_wrong_manufacturer_and_pachinko_are_never_matched(self):
        self.assertEqual(matcher.candidate_matches(model(maker='他社'), [product()], 'yamasa'), [])
        self.assertEqual(matcher.candidate_matches(model(kind='pachinko'), [product()], 'yamasa'), [])

    def test_kitadenshi_never_uses_title_guessing(self):
        rows = [product('テストシリーズ', 'https://www.kitadenshi.co.jp/slot/test/', ['S別機種KK'])]
        self.assertEqual(matcher.candidate_matches(model('SテストシリーズKK', '株式会社北電子'), rows, 'kitadenshi'), [])

    def test_unique_match_keeps_identity_raw_model_and_existing_aliases(self):
        row = model()
        row['aliases'] = ['モンキー5']
        result, report = matcher.enrich({'machines': [row]}, source([product()]))
        matched = result['machines'][0]
        self.assertEqual(matched['name'], 'スマスロモンキーターンⅤ')
        self.assertEqual(matched['modelName'], row['modelName'])
        self.assertEqual(matched['id'], row['id'])
        self.assertEqual(matched['aliases'], row['aliases'])
        self.assertEqual(row['nameOrigin'], 'notice')  # Input is not mutated.
        self.assertEqual(report['counts'], {'matched': 1, 'pending': 0, 'total': 1})

    def test_ambiguous_candidates_remain_pending(self):
        rows = [product(), product('スマスロ モンキーターンⅤ', 'https://yamasa-next.co.jp/slot/other/')]
        result, report = matcher.enrich({'machines': [model()]}, source(rows))
        self.assertEqual(result['machines'][0]['name'], 'Ｌモンキーターン５ＣＥ')
        self.assertEqual(report['pending'][0]['reason'], 'ambiguous')

    def test_unknown_products_and_unsupported_makers_remain_unchanged(self):
        rows = [model('L未発表機種XX'), model(maker='他社')]
        result, report = matcher.enrich({'machines': rows}, source([product()]))
        self.assertEqual([r['name'] for r in result['machines']], [r['name'] for r in rows])
        self.assertEqual(len(report['pending']), 2)

    def test_cached_source_is_marked_stale_not_as_a_fresh_confirmation(self):
        result, _ = matcher.enrich({'machines': [model()]}, source([product()], 'stale'))
        self.assertTrue(result['machines'][0]['manufacturerMatch']['stale'])

    def test_failed_download_retains_last_successful_products(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base/'catalog.json').write_text(json.dumps({'machines': [model()]}))
            (base/'state.json').write_text(json.dumps(source([product()])))
            args = ['match', '--catalog', str(base/'catalog.json'), '--state', str(base/'state.json'), '--report', str(base/'report.json')]
            with patch('sys.argv', args), patch.object(matcher, 'collect_source', side_effect=TimeoutError('timeout')):
                matcher.main()
            result = json.loads((base/'catalog.json').read_text())
            self.assertEqual(result['machines'][0]['name'], 'スマスロモンキーターンⅤ')
            self.assertTrue(result['machines'][0]['manufacturerMatch']['stale'])
            self.assertEqual(json.loads((base/'state.json').read_text())['yamasa']['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
