import { useSearchParams } from "react-router-dom";
import {
  Box,
  Card,
  CardContent,
  Chip,
  TextField,
  Typography,
} from "@mui/material";
import { useApi } from "../hooks";
import { DetailLink, PageState, Rows, Section } from "../components/common";

const TYPE_RESOURCE: Record<string, string> = {
  material: "materials",
  concept: "concepts",
  bank_question: "bank-questions",
  session_question: "session-questions",
  session: "sessions",
  conversation: "conversations",
};

const GROUP_LABELS: Record<string, string> = {
  materials: "材料",
  concepts: "概念",
  questions: "题",
  sessions: "会话 / 自由对话",
};

export function GlobalSearch() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const needle = query.trim();
  const result = useApi<any>(
    needle ? `/search?q=${encodeURIComponent(needle)}&limit=30` : null,
  );

  const setQuery = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("q", value);
    else next.delete("q");
    setParams(next, { replace: true });
  };

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        全局搜索
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        材料、概念、题库题、会话题、学习会话与自由对话。
      </Typography>
      <TextField
        fullWidth
        autoFocus
        label="关键词"
        value={query}
        onChange={(event) => setQuery(event.target.value)}        placeholder="例如：MVP、切块、混合检索"
      />

      {!needle ? (
        <Typography color="text.secondary" sx={{ mt: 3 }}>
          输入关键词开始。
        </Typography>
      ) : (
        <PageState
          loading={result.loading}
          error={result.error}
          empty={!result.data || result.data.counts?.questions + result.data.counts?.materials + result.data.counts?.concepts + result.data.counts?.sessions === 0}
          emptyText="没有匹配。换同义词或英文术语再试。"
          onRetry={result.reload}
        >
          {result.data && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="body2" color="text.secondary">
                “{result.data.query}”
              </Typography>
              {Object.entries(GROUP_LABELS).map(([key, label]) => {
                const items = result.data.groups?.[key] || [];
                if (items.length === 0) return null;
                return (
                  <Section key={key} title={label} count={items.length}>
                    <Rows
                      items={items}
                      render={(item: any) => (
                        <Card variant="outlined">
                          <CardContent
                            sx={{ py: 1, "&:last-child": { pb: 1 } }}
                          >
                            <Typography>
                              <DetailLink
                                resource={TYPE_RESOURCE[item.type]}
                                id={item.id}
                                label={item.title || item.id}
                              />{" "}
                              <Chip
                                size="small"
                                variant="outlined"
                                label={item.type}
                              />
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {item.subtitle}
                            </Typography>
                          </CardContent>
                        </Card>
                      )}
                    />
                  </Section>
                );
              })}
            </Box>
          )}
        </PageState>
      )}
    </Box>
  );
}
