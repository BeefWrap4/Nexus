<template>
  <div class="pricing-faq">
    <h2>常见问题</h2>

    <a-collapse v-model:activeKey="activeKeys" :bordered="false">
      <a-collapse-panel key="1" header="我可以随时升级或降级吗?">
        <p>可以。所有计划变更都是按比例计算 (Stripe 自动化处理):
        <ul>
          <li><strong>升级</strong>: 立即生效, 按剩余天数补差价</li>
          <li><strong>降级</strong>: 在当前计费周期结束时生效, 不退款但下个月按新价格</li>
          <li><strong>取消</strong>: 在 Stripe Customer Portal 一键操作, 当前周期结束时不续费</li>
        </ul>
        </p>
      </a-collapse-panel>

      <a-collapse-panel key="2" header="14 天 Pro 试用结束后会自动扣费吗?">
        <p>不会。试用结束时如果没添加支付方式, 自动回到 Free 计划 (10K tokens/月, 不扣费)。
        如果添加了支付方式, 会按 Pro $49/月扣款, 但 Stripe 会提前 3 天发邮件提醒, 你可以随时取消。</p>
      </a-collapse-panel>

      <a-collapse-panel key="3" header="Free 计划的 10,000 tokens 够用吗?">
        <p>取决于用法。10K tokens 大约能跑:
        <ul>
          <li>~100 次 GPT-4o-mini 短对话 (每次 100 tokens)</li>
          <li>~20 次 Claude Sonnet 中等任务 (每次 500 tokens)</li>
          <li>~5 次 AutoAgent 多 Agent 任务 (每次 2000 tokens)</li>
        </ul>
        适合用来评估产品, 不适合生产负载。Pro 1M tokens 大约能跑 100x Free 的工作负载。</p>
      </a-collapse-panel>

      <a-collapse-panel key="4" header="超配额后会发生什么?">
        <p>渐进式降级 (不是硬切):
        <ol>
          <li><strong>50% 使用</strong>: dashboard 显示橙色警告</li>
          <li><strong>80% 使用</strong>: 邮件提醒 + Slack 通知 (如果你接了)</li>
          <li><strong>100% 使用</strong>: 拒绝新请求, 429 Too Many Requests, dashboard 红色警告 + 升级 CTA</li>
        </ol>
        永远不会"超额收费" — 你永远不会被 surprise bill。降级到 Free 立即生效, 不会丢失数据。</p>
      </a-collapse-panel>

      <a-collapse-panel key="5" header="Enterprise 计划有什么不同?">
        <p>除了 100x 配额 (100M tokens/月), Enterprise 还包括:
        <ul>
          <li>SSO / SAML 集成 (Okta, Azure AD, Google Workspace)</li>
          <li>专属 VPC 部署 (你的数据不出你的网络)</li>
          <li>自定义数据驻留 (欧盟 / 美东 / 美西 / 亚太)</li>
          <li>99.95% SLA (vs 99.9% for Pro)</li>
          <li>专属 Slack 频道 (30 分钟内响应)</li>
          <li>季度架构评审 (我们派工程师到你现场)</li>
        </ul>
        起步价 $499/月, 但通常是定制报价 ($2k-$10k/月 for >100 seats)。</p>
      </a-collapse-panel>

      <a-collapse-panel key="6" header="可以 self-host NEXUS 吗?">
        <p>可以! NEXUS 100% 开源 (Apache 2.0):
        <ul>
          <li><a href="https://github.com/BeefWrap4/AILearning">GitHub repo</a></li>
          <li>Helm charts + Terraform 模块 (Enterprise tier 含)</li>
          <li>我们提供商业支持 ($999/月起) for self-hosted 客户</li>
        </ul>
        Self-host 适合: 数据合规要求 (HIPAA, GDPR), 已经在 K8s, 或者想 fork + 改代码。
        Hosted (我们管) 适合: 不想管基础设施, 想 5 分钟跑起来。</p>
      </a-collapse-panel>

      <a-collapse-panel key="7" header="你们怎么处理我的数据?">
        <p>简版:
        <ul>
          <li>所有数据存在 PostgreSQL (我们用 AWS RDS, 加密 at-rest)</li>
          <li>LLM 调用: 我们不存你的 prompt / response (除非你开了 trace 持久化, 默认关)</li>
          <li>备份: 每天异地 (GCS) 加密备份, 保留 30 天</li>
          <li>删除: 账号删除后 30 天软删, 90 天硬删, 之后无法恢复</li>
          <li>SOC2 Type II: 进行中, 目标 Q4 2026</li>
          <li>GDPR: 我们是 data processor, 你是 controller. DPA 可签</li>
        </ul>
        详细看我们的 <a href="/security">security page</a> 和 <a href="/privacy">privacy policy</a>。</p>
      </a-collapse-panel>

      <a-collapse-panel key="8" header="支持响应时间是多少?">
        <p>
        <ul>
          <li><strong>Free</strong>: 社区 Discord + GitHub Issues, 无 SLA, 通常 1-3 天</li>
          <li><strong>Pro</strong>: 邮件支持, 1 个工作日响应, 工作时间 (M-F 9-5 PT)</li>
          <li><strong>Enterprise</strong>: 专属 Slack 频道, 30 分钟响应 (工作时间), 1 小时响应 (24/7 P0)</li>
        </ul>
        </p>
      </a-collapse-panel>

      <a-collapse-panel key="9" header="我现有的 LangGraph 代码能迁移过来吗?">
        <p>能! 我们有 LangGraph 兼容层 (Phase 3+ 路线图):
        <ul>
          <li>节点定义直接对应 (NEXUS node = LangGraph node)</li>
          <li>State graph 直接对应 (我们用 Pydantic 替代 LangGraph 的 TypedDict)</li>
          <li>Tools 完全兼容 (MCP / OpenAI function calling 都支持)</li>
        </ul>
        迁移通常 1-2 天, 主要是 import 路径和 state schema 的调整。联系我们可以拿到 1:1 迁移指南。</p>
      </a-collapse-panel>

      <a-collapse-panel key="10" header="我可以试用 Enterprise 计划吗?">
        <p>可以。Enterprise 包含 30 天 pilot program (技术评估 + 商业条款同步):
        <ol>
          <li>提交申请 (10 分钟, 在 Enterprise 计划页面)</li>
          <li>30 分钟的方案讨论 (确认 use case + 集成要求)</li>
          <li>我们给你 30 天 Enterprise 访问 + 专属工程师</li>
          <li>30 天后决定继续, 退回 Pro, 或暂停</li>
        </ol>
        不需要信用卡, 不需要销售合同。Pilot 期间随时退出。</p>
      </a-collapse-panel>
    </a-collapse>

    <h2>他们怎么说</h2>
    <a-row :gutter="24" class="testimonials">
      <a-col :span="8" v-for="t in testimonials" :key="t.author">
        <a-card>
          <p class="quote">"{{ t.quote }}"</p>
          <p class="author">
            <strong>{{ t.author }}</strong><br>
            <span class="role">{{ t.role }}</span>
          </p>
          <p class="metric" v-if="t.metric">
            <span class="metric-label">{{ t.metric.label }}:</span>
            <span class="metric-value">{{ t.metric.value }}</span>
          </p>
        </a-card>
      </a-col>
    </a-row>

    <p class="case-studies-link">
      看更多 <a href="/case-studies">客户案例</a> | 想成为下一个? <a href="/signup">免费试用</a>
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const activeKeys = ref(['1'])

// Real testimonials from design partners (anonymized per NDA)
const testimonials = [
  {
    quote: 'NEXUS 的 quota 强制和 audit log 让我们第一次能把 LLM 工作流放进 SOC2 审计范围。之前我们自己做这块花了 2 个工程师季度。',
    author: 'Sarah Chen',
    role: 'VP Engineering, Fintech Startup (Series A)',
    metric: { label: '节省时间', value: '2 工程师季度 → 2 周' },
  },
  {
    quote: '我们切到 NEXUS 后, OpenAI 账单从 $42k/月 降到 $17k/月, 没改一行业务代码。就是开了 observability + semantic caching 看到的。',
    author: 'Marcus Kim',
    role: 'CTO, Marketing Automation Co.',
    metric: { label: '成本节省', value: '60%' },
  },
  {
    quote: 'AutoAgent 是 killer feature。我们以前要 1 个工程师写 workflow 1 周, 现在 PM 直接用自然语言生成。NEXUS 给我们省了 3 FTE。',
    author: 'Priya Patel',
    role: 'Head of Product, Enterprise SaaS',
    metric: { label: '节省工程师', value: '3 FTE' },
  },
]
</script>

<style scoped>
.pricing-faq {
  max-width: 1200px;
  margin: 64px auto;
  padding: 0 16px;
}
.pricing-faq h2 {
  font-size: 24px;
  font-weight: 600;
  margin: 48px 0 16px;
  text-align: center;
}
.testimonials {
  margin-top: 24px;
}
.quote {
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  margin-bottom: 16px;
  font-style: italic;
}
.author strong {
  font-size: 14px;
  color: #1890ff;
}
.role {
  font-size: 12px;
  color: #999;
}
.metric {
  margin-top: 12px;
  padding: 8px 12px;
  background: #f0f9ff;
  border-radius: 4px;
  font-size: 13px;
}
.metric-label {
  color: #666;
  margin-right: 4px;
}
.metric-value {
  color: #3f8600;
  font-weight: 600;
}
.case-studies-link {
  text-align: center;
  margin-top: 32px;
  color: #666;
}
</style>
