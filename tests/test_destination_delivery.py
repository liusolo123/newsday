"""Platform payload validation and delivery failure classification tests."""

import unittest
from unittest.mock import Mock, patch

import requests

from app.services.destinations import WebhookSendError, build_webhook_payload, send_webhook
from app.workers.dispatch import delivery_error_details


class DestinationDeliveryTests(unittest.TestCase):
    def _response(self, payload):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    def test_feishu_payload_and_success_response_are_validated(self):
        self.assertEqual(
            build_webhook_payload("feishu", "摘要"),
            {"msg_type": "text", "content": {"text": "摘要"}},
        )
        with patch("app.services.destinations.requests.post", return_value=self._response({"code": 0})) as post:
            send_webhook("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/example", "摘要")
        self.assertEqual(post.call_args.kwargs["timeout"], 10)

    def test_wecom_payload_and_success_response_are_validated(self):
        self.assertEqual(
            build_webhook_payload("wecom", "摘要"),
            {"msgtype": "text", "text": {"content": "摘要"}},
        )
        with patch("app.services.destinations.requests.post", return_value=self._response({"errcode": 0})):
            send_webhook("wecom", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=example", "摘要")

    def test_platform_rejection_is_not_retried(self):
        with patch("app.services.destinations.requests.post", return_value=self._response({"code": 19021})):
            with self.assertRaises(WebhookSendError) as raised:
                send_webhook("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/example", "摘要")
        self.assertEqual(delivery_error_details(raised.exception), ("feishu_19021", False))

    def test_http_and_network_failures_have_correct_retry_policy(self):
        response = Mock(status_code=429)
        http_error = requests.HTTPError(response=response)
        self.assertEqual(delivery_error_details(http_error), ("http_429", True))
        self.assertEqual(delivery_error_details(requests.ConnectionError()), ("network_error", True))


if __name__ == "__main__":
    unittest.main()
