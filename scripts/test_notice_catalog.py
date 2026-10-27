import unittest
from copy import deepcopy
from unittest.mock import patch

import build_notice_catalog as catalog


class Page:
    def __init__(self, rows):
        self.rows = rows

    def extract_text(self):
        return "検定遊技機一覧表（福井県公安委員会）"

    def extract_tables(self):
        return [[['番号', '申請者', '種類', '型式名', '製造業者名', '検定番号', '公示日']] + self.rows]


class Pdf:
    def __init__(self, rows):
        self.pages = [Page(rows)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class CatalogTests(unittest.TestCase):
    row = ['1', '株式会社試験', '回胴式遊技機', 'Ｌテスト\nＡ１', '申請者に同じ', '６Ｓ０００１', '令和８年１０月２３日']
    url = f"https://{catalog.HOST}{catalog.PDF_PREFIX}test.pdf"

    def parse(self, rows):
        with patch.object(catalog.pdfplumber, 'open', return_value=Pdf(rows)):
            return catalog.parse_pdf(b'pdf', self.url)

    def test_wrapped_names_and_date_are_preserved(self):
        row = self.parse([self.row])[0]
        self.assertEqual(row['modelName'], 'ＬテストＡ１')
        self.assertEqual(row['manufacturer'], '株式会社試験')
        self.assertEqual(row['noticeDate'], '2026-10-23')
        self.assertNotIn('releasedOn', row)

    def test_missing_rows_fail_instead_of_silently_publishing(self):
        second = [*self.row]
        second[0] = '3'
        with self.assertRaises(ValueError):
            self.parse([self.row, second])

    def test_shizuoka_uses_examination_date_and_wrapped_approval(self):
        row = [*self.row]
        row[5] = '第６Ｓ０００１号'
        with patch.object(catalog.pdfplumber, 'open', return_value=Pdf([row])):
            result = catalog.parse_pdf(b'pdf', 'https://www.pref.shizuoka.jp/test.pdf')[0]
        self.assertEqual(result['examinedOn'], '2026-10-23')
        self.assertNotIn('noticeDate', result)
        self.assertEqual(result['approvalNumber'], '6S0001')

    def test_yamagata_does_not_collect_applicant_address_or_representative(self):
        page = Page([])
        page.extract_text = lambda: '公 示 令和８年10月22日 山形県公安委員会'
        page.extract_tables = lambda: [[['住所付き申請者', '代表者氏名', '回胴式遊技機', 'Ｌテスト\nＡ１', '株式会社試\n験', '第６Ｓ０００１号', '３年間']]]
        pdf = Pdf([])
        pdf.pages = [page]
        with patch.object(catalog.pdfplumber, 'open', return_value=pdf):
            result = catalog.parse_pdf(b'pdf', 'https://www.pref.yamagata.jp/test.pdf')[0]
        self.assertEqual(result['noticeDate'], '2026-10-22')
        self.assertEqual(result['manufacturer'], '株式会社試験')
        self.assertNotIn('代表者氏名', str(result))
        self.assertNotIn('住所付き申請者', str(result))

    def test_broken_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            self.parse([self.row[:-1]])

    def test_official_category_typo_keeps_provenance(self):
        wrong = [*self.row]
        wrong[2] = 'ぱちんこ'
        row = self.parse([wrong])[0]
        self.assertEqual(row['kind'], 'pachislot')
        self.assertEqual(row['noticeKind'], 'ぱちんこ')
        self.assertEqual(row['classificationBasis'], 'model-prefix')

    def test_overrides_match_whole_model_and_manufacturer(self):
        rows = self.parse([self.row])
        other = {**deepcopy(rows[0]), 'id': 'other', 'modelName': 'ＬテストＡ２'}
        overrides = [{'manufacturer': '株式会社試験', 'modelName': 'Lテスト A1', 'name': 'テスト', 'reading': 'てすと', 'aliases': ['試験機']}]
        updated = catalog.apply_overrides(rows + [other], overrides)
        self.assertEqual(updated[0]['name'], 'テスト')
        self.assertEqual(updated[0]['modelName'], 'ＬテストＡ１')
        self.assertEqual(updated[1]['name'], 'LテストA1')
        self.assertEqual(updated[0]['nameOrigin'], 'curated')

    def test_previous_notices_survive_archive_rotation_and_deduplicate(self):
        row = self.parse([self.row])[0]
        previous = {'machines': [row]}
        result = catalog.build_catalog([[row]], previous, [], [])
        self.assertEqual(len(result['machines']), 1)
        result = catalog.build_catalog([], previous, [], [])
        self.assertEqual(result['machines'][0]['id'], row['id'])
        with self.assertRaises(ValueError):
            catalog.build_catalog([], {}, [], [])

    def test_discovery_excludes_non_notice_pdf_and_external_hosts(self):
        parser = catalog.NoticeLinks()
        parser.feed('<a href="./yuugikikenteikouji_d/fil/test.pdf">公示</a><a href="https://elsewhere.test/a.pdf">別サイト</a><a href="./other.pdf">その他</a>')
        self.assertEqual(parser.links, [self.url])

    def test_robots_wildcards_are_honored(self):
        robots = '\ufeffUser-agent: ndl-japan\nAllow: /\n\nUser-agent: *\nDisallow: /*koji_*.pdf$'
        self.assertTrue(catalog.robots_allowed(robots, self.url))
        self.assertFalse(catalog.robots_allowed(robots, f'https://{catalog.HOST}/koji_private.pdf'))
        self.assertFalse(catalog.robots_allowed('User-agent: *\nDisallow: /', self.url))


if __name__ == '__main__':
    unittest.main()
