import { useState } from "react";
import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Checkbox,
  Chip,
  FormControlLabel,
  Typography,
} from "@mui/material";
import { useApi } from "../hooks";
import { RepairPlan } from "../components/RepairPlan";
import {
  BackToList,
  CountCards,
  DetailLink,
  Field,
  PageState,
  ProvenanceChip,
  Rows,
  Section,
} from "../components/common";

function Header({
  kind,
  title,
  sub,
}: {
  kind: string;
  title: string;
  sub?: ReactNode;
}) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="overline" color="text.secondary">
        {kind}
      </Typography>
      <Typography variant="h4">{title}</Typography>
      {sub && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {sub}
        </Typography>
      )}
    </Box>
  );
}

export function MaterialShow() {
  const { id } = useParams();
  const [history, setHistory] = useState(false);
  const { data, loading, error, reload } = useApi<any>(
    id
      ? `/material/${encodeURIComponent(id)}?history=${history ? 1 : 0}`
      : null,
    [history],
  );

  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList resource="materials" label="材料列表" />
          <Header
            kind={`材料 · ${data.material.status}`}
            title={data.material.title}
            sub={
              <>
                <code>{data.material.path}</code>
                <br />
                {data.material.source_url || "无 source_url"} · v
                {data.material.version} · {data.material.format}
              </>
            }
          />
          <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
            {(data.versions || []).map((item: any) => (
              <Chip
                key={item.version}
                size="small"
                color={item.current ? "success" : "default"}
                variant={item.current ? "filled" : "outlined"}
                label={`v${item.version} · ${item.total} 块${item.current ? " · 当前" : ""}`}
              />
            ))}
            <FormControlLabel
              control={
                <Checkbox
                  checked={history}
                  onChange={(event) => setHistory(event.target.checked)}
                />
              }
              label="含历史版本"
            />
          </Box>
          <CountCards
            items={[
              ["块", data.counts.chunks],
              ["父块", data.counts.parents],
              ["子块", data.counts.children],
              ["概念", data.counts.concepts],
              ["题库题", data.counts.bank_questions],
              ["会话题", data.counts.session_questions],
              ["会话", data.counts.sessions],
              ["自由对话引用", data.counts.citations],
              ["块级", data.counts.provenance.chunk],
              ["URL 级", data.counts.provenance.url],
              ["仅概念级", data.counts.provenance.concept],
            ]}
          />

          <Section title="概念" count={data.counts.concepts}>
            <Rows
              items={data.concepts}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="concepts"
                      id={item.id}
                      label={item.name}
                    />{" "}
                    <Chip
                      size="small"
                      label={`掌握度 ${item.mastery} · ${item.mastery_label}`}
                    />{" "}
                    <Chip size="small" variant="outlined" label={item.status} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.plain_def}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    出处：{item.heading_path || "无"} · 版本{" "}
                    {(item.versions || []).join(", ")} ·{" "}
                    {item.is_primary ? "主出处" : "次出处"}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="题库题" count={data.counts.bank_questions}>
            <Rows
              items={data.bank_questions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="bank-questions"
                      id={item.id}
                      label={item.question_text}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.id} · {item.concept_id} · {item.kind}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="会话题" count={data.counts.session_questions}>
            <Rows
              items={data.session_questions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="session-questions"
                      id={item.id}
                      label={item.question_text}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    #{item.id} ·{" "}
                    <DetailLink
                      resource="sessions"
                      id={item.session_id}
                      label={item.session_id}
                    />{" "}
                    · 分数 {item.score ?? "未评分"} ·{" "}
                    {item.question_type || item.question_bank_id || "生成题"}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="会话" count={data.counts.sessions}>
            <Rows
              items={data.sessions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="sessions"
                      id={item.session_id}
                      label={`学习会话 · ${item.date || item.session_id}`}
                    />{" "}
                    <Chip size="small" label={item.agent_status || ""} />{" "}
                    <Chip
                      size="small"
                      variant="outlined"
                      label={item.final_status || "未结算"}
                    />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.question_count || 0} 道题 · 分数{" "}
                    {item.session_score ?? "—"}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="自由对话引用" count={data.counts.citations}>
            <Rows
              items={data.citations}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="conversations"
                      id={item.conversation_id}
                      label={item.conversation_title}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.role} · {item.excerpt}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="块" count={data.counts.chunks}>
            <Accordion>
              <AccordionSummary>
                展开 {data.counts.chunks} 个块
              </AccordionSummary>
              <AccordionDetails>
                <Rows
                  items={data.chunks.items}
                  render={(item: any) => (
                    <>
                      <Typography>
                        v{item.version} · {item.level} ·{" "}
                        {item.heading_path || "无标题"}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {item.id}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {item.preview}
                      </Typography>
                    </>
                  )}
                />
              </AccordionDetails>
            </Accordion>
          </Section>

          <RepairPlan repair={data.repair} />
        </Box>
      )}
    </PageState>
  );
}

export function ConceptShow() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<any>(
    id ? `/concept/${encodeURIComponent(id)}` : null,
  );
  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList resource="concepts" label="概念列表" />
          <Header
            kind="概念"
            title={data.concept.name}
            sub={
              <>
                <code>{data.concept.id}</code> · 难度{" "}
                {data.concept.difficulty ?? "—"}
              </>
            }
          />
          <Typography sx={{ mb: 1 }}>{data.concept.plain_def}</Typography>
          <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
            <Chip
              label={`掌握度 ${data.state.mastery} · ${data.state.mastery_label}`}
            />
            <Chip variant="outlined" label={data.state.status} />
            <Chip
              variant="outlined"
              label={`最近 ${data.state.last_seen || "—"}`}
            />
            <Chip
              variant="outlined"
              label={`复习到期 ${data.state.review_due_at || "—"}`}
            />
            {(data.concept.aliases || []).map((alias: string) => (
              <Chip key={alias} variant="outlined" label={`别名：${alias}`} />
            ))}
            {(data.concept.prerequisites || []).map((item: string) => (
              <Chip key={item} variant="outlined" label={`前置：${item}`} />
            ))}
          </Box>
          {data.concept.source && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              YAML 出处：{data.concept.source.url}
              <br />
              {data.concept.source.excerpt}
            </Typography>
          )}
          <CountCards
            items={[
              ["出处", data.counts.sources],
              ["题库题", data.counts.bank_questions],
              ["会话题", data.counts.session_questions],
              ["会话", data.counts.sessions],
              ["后继概念", data.counts.dependents],
            ]}
          />

          <Section title="出处" count={data.counts.sources}>
            <Rows
              items={data.sources}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="materials"
                      id={item.material_id}
                      label={item.material_title || item.material_id}
                    />{" "}
                    <Chip size="small" label={`v${item.version}`} />{" "}
                    <Chip
                      size="small"
                      color={item.is_current ? "success" : "default"}
                      variant={item.is_current ? "filled" : "outlined"}
                      label={item.is_current ? "当前版本" : "历史版本"}
                    />{" "}
                    {item.is_primary && <Chip size="small" label="主出处" />}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.heading_path || "无标题"} · {item.chunk_id}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.excerpt}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="题库题" count={data.counts.bank_questions}>
            <Rows
              items={data.bank_questions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="bank-questions"
                      id={item.id}
                      label={item.question_text}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.id} · {item.kind}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="会话题" count={data.counts.session_questions}>
            <Rows
              items={data.session_questions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="session-questions"
                      id={item.id}
                      label={item.question_text}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    #{item.id} ·{" "}
                    <DetailLink
                      resource="sessions"
                      id={item.session_id}
                      label={item.session_id}
                    />{" "}
                    · 分数 {item.score ?? "未评分"}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="会话" count={data.counts.sessions}>
            <Rows
              items={data.sessions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="sessions"
                      id={item.session_id}
                      label={`学习会话 · ${item.date || item.session_id}`}
                    />{" "}
                    <Chip size="small" label={item.agent_status || ""} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.question_count || 0} 道题 · 分数{" "}
                    {item.session_score ?? "—"}
                  </Typography>
                </>
              )}
            />
          </Section>

          <Section title="后继概念" count={data.counts.dependents}>
            <Rows
              items={data.dependents}
              render={(item: any) => (
                <DetailLink
                  resource="concepts"
                  id={item.id}
                  label={item.name}
                />
              )}
            />
          </Section>

          <Section title="最近一次有评分的作答">
            {data.latest_assessment ? (
              <CountCards
                items={[
                  ["日期", data.latest_assessment.date],
                  ["均分", data.latest_assessment.avg_score],
                  ["最低分", data.latest_assessment.min_score],
                  ["题数", data.latest_assessment.scored],
                  ["会话 ID", data.latest_assessment.session_id],
                ]}
              />
            ) : (
              <Typography color="text.secondary">无</Typography>
            )}
          </Section>

          <RepairPlan repair={data.repair} />
        </Box>
      )}
    </PageState>
  );
}

function QuestionDetail({ bank }: { bank: boolean }) {
  const { id } = useParams();
  const path = id
    ? bank
      ? `/question?bank_id=${encodeURIComponent(id)}`
      : `/question?session_question_id=${encodeURIComponent(id)}`
    : null;
  const { data, loading, error, reload } = useApi<any>(path);
  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList
            resource={bank ? "bank-questions" : "session-questions"}
            label={bank ? "题库题列表" : "会话题列表"}
          />
          <Header
            kind={`${data.origin.label}${bank ? ` · ${data.question.id}` : ` · #${data.question.id}`}`}
            title={data.question.question_text}
            sub={
              <>
                {data.question.concept_id || ""}{" "}
                <ProvenanceChip provenance={data.provenance} />
              </>
            }
          />
          <Section title="概念">
            {data.concept ? (
              <>
                <DetailLink
                  resource="concepts"
                  id={data.concept.id}
                  label={data.concept.name}
                />
                <Typography variant="body2" color="text.secondary">
                  {data.concept.plain_def}
                </Typography>
              </>
            ) : (
              <Typography color="text.secondary">无</Typography>
            )}
          </Section>
          <Section title="材料">
            {data.material ? (
              <>
                <DetailLink
                  resource="materials"
                  id={data.material.id}
                  label={data.material.title}
                />
                <Typography variant="body2" color="text.secondary">
                  {data.material.path} · v{data.material.version}
                </Typography>
              </>
            ) : (
              <Typography color="text.secondary">未匹配</Typography>
            )}
          </Section>
          {data.chunk && (
            <Section title="命中块">
              <Typography variant="body2" color="text.secondary">
                {data.chunk.id} · v{data.chunk.material_version} ·{" "}
                {data.chunk.heading_path || ""}
              </Typography>
            </Section>
          )}
          {data.origin.meta && Object.keys(data.origin.meta).length > 0 && (
            <Section title="生成元数据">
              <Box
                component="pre"
                sx={{ p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 12 }}
              >
                {JSON.stringify(data.origin.meta, null, 2)}
              </Box>
            </Section>
          )}
          {!bank && (
            <Section title="作答">
              <Field label="回答">{data.question.answer_text || "未作答"}</Field>
              <Field label="分数">{data.question.score ?? "未评分"}</Field>
              <Field label="反馈">{data.question.feedback || "无"}</Field>
            </Section>
          )}
          {data.usage && (
            <Section title="使用记录" count={data.counts.usage}>
              <Rows
                items={data.usage}
                render={(item: any) => (
                  <>
                    <Typography>
                      <DetailLink
                        resource="sessions"
                        id={item.session_id}
                        label={`学习会话 · ${item.date || item.session_id}`}
                      />{" "}
                      <Chip size="small" label={item.session_status || ""} />
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      分数 {item.score ?? "未评分"} ·{" "}
                      {item.answer_text || "无回答"}
                    </Typography>
                  </>
                )}
              />
            </Section>
          )}
          {data.session && (
            <Section title="所在会话">
              <DetailLink
                resource="sessions"
                id={data.session.session_id}
                label={data.session.date || data.session.session_id}
              />{" "}
              · {data.session.agent_status} · {data.session.final_status || "未结算"}
            </Section>
          )}
          <RepairPlan repair={data.repair} />
        </Box>
      )}
    </PageState>
  );
}

export function BankQuestionShow() {
  return <QuestionDetail bank />;
}

export function SessionQuestionShow() {
  return <QuestionDetail bank={false} />;
}

export function SessionShow() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<any>(
    id ? `/session/${encodeURIComponent(id)}` : null,
  );
  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList resource="sessions" label="学习会话列表" />
          <Header
            kind="学习会话"
            title={data.session.date || data.session.session_id}
            sub={
              <>
                <code>{data.session.session_id}</code> · {data.session.kind} ·{" "}
                {data.session.agent_status} ·{" "}
                {data.session.final_status || "未结算"}
              </>
            }
          />
          <CountCards
            items={[
              ["题目", data.counts.questions],
              ["已评分", data.counts.scored],
              ["追问/讲解", data.counts.notes],
              ["分数", data.session.session_score ?? "—"],
              ["输入", data.session.input_mode || "—"],
              ["时长", data.session.minutes != null ? `${data.session.minutes} 分钟` : "—"],
            ]}
          />
          <Section title="题目" count={data.counts.questions}>
            <Rows
              items={data.questions}
              render={(item: any) => (
                <>
                  <Typography>
                    <DetailLink
                      resource="session-questions"
                      id={item.id}
                      label={item.question_text}
                    />{" "}
                    <ProvenanceChip provenance={item.provenance} />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    #{item.id} ·{" "}
                    <DetailLink
                      resource="concepts"
                      id={item.concept_id}
                      label={item.concept_name || item.concept_id}
                    />{" "}
                    · {item.origin?.label || ""} · 分数{" "}
                    {item.score ?? "未评分"}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.answer_text || "未作答"}
                  </Typography>
                </>
              )}
            />
          </Section>
          <Section title="追问 / 讲解" count={data.counts.notes}>
            <Rows
              items={data.notes}
              render={(item: any) => (
                <>
                  <Typography>
                    {item.mode}
                    {item.question_id ? ` · 题目 #${item.question_id}` : ""}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    输入：{item.input_text}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    输出：{item.output_text}
                  </Typography>
                </>
              )}
            />
          </Section>
          <RepairPlan repair={data.repair} />
        </Box>
      )}
    </PageState>
  );
}

export function ConversationShow() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<any>(
    id ? `/conversation/${encodeURIComponent(id)}` : null,
  );
  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList resource="conversations" label="自由对话列表" />
          <Header
            kind="自由对话"
            title={data.conversation.title || "未命名对话"}
            sub={
              <>
                <code>{data.conversation.id}</code> ·{" "}
                {data.conversation.updated_at}
              </>
            }
          />
          <CountCards
            items={[
              ["消息", data.counts.messages],
              ["材料引用", data.counts.material_sources],
              ["网页引用", data.counts.web_sources],
            ]}
          />
          <Section title="消息" count={data.counts.messages}>
            <Rows
              items={data.messages}
              render={(message: any) => (
                <>
                  <Typography variant="caption" color="text.secondary">
                    {message.role} · {message.created_at}
                    {message.mode ? ` · ${message.mode}` : ""}
                  </Typography>
                  <Typography sx={{ whiteSpace: "pre-wrap", my: 0.5 }}>
                    {message.text}
                  </Typography>
                  {(message.sources || []).map((source: any, index: number) => (
                    <Box
                      key={`${message.id}-${index}`}
                      sx={{ p: 1, my: 0.5, bgcolor: "action.hover", borderRadius: 1 }}
                    >
                      <Typography variant="body2">
                        {source.material_id ? (
                          <DetailLink
                            resource="materials"
                            id={source.material_id}
                            label={source.title || source.material_id}
                          />
                        ) : (
                          source.title || source.url
                        )}{" "}
                        <Chip
                          size="small"
                          variant="outlined"
                          label={source.kind === "material" ? "材料引用" : "网页"}
                        />
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {source.url}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {source.excerpt}
                      </Typography>
                    </Box>
                  ))}
                </>
              )}
            />
          </Section>
          <RepairPlan repair={data.repair} />
        </Box>
      )}
    </PageState>
  );
}

export function PipelineRunShow() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<any>(
    id ? `/pipeline-runs/${encodeURIComponent(id)}` : null,
  );
  return (
    <PageState loading={loading} error={error} onRetry={reload}>
      {data && (
        <Box>
          <BackToList resource="pipeline-runs" label="管线运行列表" />
          <Header
            kind="管线运行"
            title={`${data.kind} · ${data.status}`}
            sub={<code>#{data.id}</code>}
          />
          <Field label="开始">{data.started_at}</Field>
          <Field label="结束">{data.finished_at || "—"}</Field>
          <Field label="输入">{data.input || "—"}</Field>
          <Field label="错误">{data.error || "无"}</Field>
          <Section title="统计">
            <Box
              component="pre"
              sx={{ p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 12 }}
            >
              {JSON.stringify(data.stats, null, 2)}
            </Box>
          </Section>
        </Box>
      )}
    </PageState>
  );
}
