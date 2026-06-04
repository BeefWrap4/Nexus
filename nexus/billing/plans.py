"""Pre-defined subscription plans."""
from nexus.billing.models import SubscriptionPlan, BillingPeriod

PLANS: dict[str, SubscriptionPlan] = {
    "free": SubscriptionPlan(
        plan_id="free", name="Free", price_usd=0.0,
        max_workflows=10, max_agents=3, max_llm_calls_per_day=100,
        max_tokens_per_month=100_000, max_crew_executions=5,
        features=["Basic workflow engine", "3 agents", "Community tools"],
    ),
    "pro": SubscriptionPlan(
        plan_id="pro", name="Professional", price_usd=49.0,
        max_workflows=100, max_agents=20, max_llm_calls_per_day=5000,
        max_tokens_per_month=5_000_000, max_crew_executions=200,
        features=["Advanced workflow engine", "20 agents", "All tools", "Priority support", "Custom prompts"],
    ),
    "enterprise": SubscriptionPlan(
        plan_id="enterprise", name="Enterprise", price_usd=299.0,
        max_workflows=1000, max_agents=100, max_llm_calls_per_day=50000,
        max_tokens_per_month=50_000_000, max_crew_executions=1000,
        features=["Unlimited workflows", "100 agents", "All tools", "Dedicated support",
                   "Custom plugins", "SSO", "Audit logs", "SLA guarantee"],
    ),
}
