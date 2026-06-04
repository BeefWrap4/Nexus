"""OpenTelemetry 链路追踪配置."""

import logging

from nexus.config import settings

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str = "nexus-api"):
    """配置 OpenTelemetry 链路追踪.

    当 ENABLE_OPENTELEMETRY=False 或 SDK 未安装时，gracefully degrade 并返回 None。
    """
    if not settings.ENABLE_OPENTELEMETRY:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)

        otlp_endpoint = getattr(
            settings, 'OTEL_EXPORTER_OTLP_ENDPOINT',
            'http://localhost:4318/v1/traces',
        )
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        logger.info(
            "OpenTelemetry tracing enabled (service=%s, endpoint=%s)",
            service_name, otlp_endpoint,
        )
        return trace.get_tracer(service_name)
    except ImportError:
        logger.warning("OpenTelemetry SDK not installed, tracing disabled")
        return None


def get_tracer():
    """获取当前 tracer."""
    from opentelemetry import trace
    return trace.get_tracer("nexus")
