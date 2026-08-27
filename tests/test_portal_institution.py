import unittest

from collectors.portal_institution import (
    build_request_url,
    has_real_image,
    normalize_date,
    parse_xml,
)


SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>OK</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <atcId>F202608210001</atcId>
        <fdSn>1</fdSn>
        <prdtClNm>지갑&gt;남성지갑</prdtClNm>
        <clrNm>검정</clrNm>
        <fdPrdtNm>검정색 반지갑</fdPrdtNm>
        <fdSbjt>검정색 반지갑을 보관 중입니다</fdSbjt>
        <fdFilePathImg>https://example.com/wallet.jpg</fdFilePathImg>
        <depPlace>야탑역</depPlace>
        <fdYmd>20260820</fdYmd>
      </item>
    </items>
    <totalCount>1</totalCount>
  </body>
</response>
"""


class PortalInstitutionCollectorTests(unittest.TestCase):
    def test_parse_xml_normalizes_item(self):
        items, total_count, result_code, result_message = parse_xml(SAMPLE_XML)

        self.assertEqual(result_code, "00")
        self.assertEqual(result_message, "OK")
        self.assertEqual(total_count, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "PORTAL_INSTITUTION")
        self.assertEqual(items[0].source_id, "F202608210001-1")
        self.assertEqual(items[0].item_name, "검정색 반지갑")
        self.assertEqual(items[0].storage_place, "야탑역")
        self.assertEqual(items[0].found_date, "2026-08-20")
        self.assertTrue(items[0].has_real_image)

    def test_encoded_key_is_not_double_encoded(self):
        url = build_request_url("abc%2Fdef%3D%3D", {"pageNo": 1})

        self.assertIn("serviceKey=abc%2Fdef%3D%3D", url)
        self.assertNotIn("%252F", url)

    def test_placeholder_image_is_not_real_image(self):
        self.assertFalse(
            has_real_image("https://minwon24.police.go.kr/images/sub/img02_no_img.gif")
        )
        self.assertFalse(has_real_image(""))
        self.assertTrue(has_real_image("https://example.com/found-item.jpg"))

    def test_date_formats_are_normalized(self):
        self.assertEqual(normalize_date("20260820"), "2026-08-20")
        self.assertEqual(normalize_date("2026-08-20"), "2026-08-20")


if __name__ == "__main__":
    unittest.main()

