"""Complete measurement carrier corresponding to chapter 05's custom SLO."""
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

reader = InMemoryMetricReader()
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
requests = metrics.get_meter('chat-slo').create_counter('http.server.requests', unit='{request}')


def record_request(status_code: int, duration_seconds: float) -> None:
    requests.add(1, {'http.route': '/chat', 'app.slo.result':
                    'bad' if status_code >= 500 or duration_seconds > 8 else 'good'})


record_request(200, .4)
record_request(503, 9)  # one bad event despite both conditions
counts = {p.attributes['app.slo.result']: p.value
          for rm in reader.get_metrics_data().resource_metrics
          for sm in rm.scope_metrics for m in sm.metrics for p in m.data.data_points}
assert counts == {'good': 1, 'bad': 1}, counts
provider.shutdown()
print('PASS one good and one bad event; 503 plus 9s counted once')
