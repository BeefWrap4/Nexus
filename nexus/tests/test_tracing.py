"""Tests for OpenTelemetry tracing setup with graceful degradation."""

import pytest
from unittest.mock import MagicMock, patch


class TestTracing:
    """OpenTelemetry tracing setup tests."""

    def test_setup_tracing_disabled(self):
        """ENABLE_OPENTELEMETRY=false 时返回 None."""
        with patch('nexus.observability.tracing.settings') as mock_settings:
            mock_settings.ENABLE_OPENTELEMETRY = False
            from nexus.observability.tracing import setup_tracing
            result = setup_tracing()
            assert result is None

    def test_setup_tracing_enabled_with_sdk(self):
        """ENABLE_OPENTELEMETRY=true 且 SDK 可用时创建 tracer."""
        # 因为这些类在 setup_tracing 函数内部通过 from-import 导入，
        # 需要 mock 在 setup_tracing 内部引用时的路径
        mock_tracer = MagicMock()
        mock_provider = MagicMock()
        mock_provider.get_tracer.return_value = mock_tracer

        mock_resource = MagicMock()

        with patch('nexus.observability.tracing.settings') as mock_settings:
            mock_settings.ENABLE_OPENTELEMETRY = True
            mock_settings.OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4318/v1/traces'

            with patch(
                'opentelemetry.sdk.trace.TracerProvider',
                return_value=mock_provider,
            ), patch(
                'opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter',
            ) as mock_exporter_cls, patch(
                'opentelemetry.sdk.resources.Resource',
                return_value=mock_resource,
            ), patch(
                'opentelemetry.trace.set_tracer_provider',
            ) as mock_set_provider:
                from nexus.observability.tracing import setup_tracing
                result = setup_tracing()

                assert result is not None
                mock_set_provider.assert_called_once()

    def test_setup_tracing_import_error(self):
        """SDK 未安装时 graceful degradation，返回 None 不崩溃."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name.startswith('opentelemetry'):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch('nexus.observability.tracing.settings') as mock_settings:
            mock_settings.ENABLE_OPENTELEMETRY = True

            with patch('builtins.__import__', side_effect=mock_import):
                from nexus.observability.tracing import setup_tracing
                result = setup_tracing()
                assert result is None

    def test_get_tracer_returns_tracer(self):
        """get_tracer 返回默认名称为 nexus 的 tracer."""
        mock_tracer = MagicMock()
        with patch(
            'opentelemetry.trace.get_tracer',
            return_value=mock_tracer,
        ) as mock_get:
            from nexus.observability.tracing import get_tracer
            result = get_tracer()
            assert result is mock_tracer
            mock_get.assert_called_once_with("nexus")
