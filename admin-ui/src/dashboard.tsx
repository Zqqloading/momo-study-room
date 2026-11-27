import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Stack,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { useApi } from "./hooks";
import { CountCards, PageState, Section, Rows } from "./components/common";
import { formatDate, Health, Task, taskLabel, taskStatusColor } from "./api";

function HealthChips({ health }: { health: Health }) {
  return (
    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1, my: 1 }}>
      {health.red.map((item) => (
        <Chip key={item.code} color="error" label={item.message} />
      ))}
      {health.yellow.map((item) => (
        <Chip key={item.code} color="warning" label={item.message} />
      ))}
      {health.red.length === 0 && health.yellow.length === 0 && (
        <Chip color="success" label="数据正常" />
      )}
      <Chip
        variant="outlined"
        label={`DB v${health.db.version}/${health.db.schema_version}`}
      />
      <Chip
        variant="outlined"
        color={health.provider.fake ? "warning" : "success"}
        label={health.provider.fake ? "provider fake" : "provider 就绪"}
      />
    </Box>
  );
}

export function Dashboard() {
  const health = useApi<Health>("/health");
  const tasks = useApi<{ data: Task[]; total: number }>("/tasks?per_page=5");

  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        内容影响面
      </Typography>
      <Typography color="text.secondary">
        只读查看内容、知识库与任务；写操作只通过任务提交。
      </Typography>
      <PageState
        loading={health.loading}
        error={health.error}
        onRetry={health.reload}
      >
        {health.data && (
          <>
            <HealthChips health={health.data} />
            <CountCards
              items={[
                ["材料", health.data.counts.materials],
                ["块", health.data.counts.chunks],
                ["概念", health.data.counts.concepts],
                ["题库题", health.data.counts.bank_questions],
                ["会话", health.data.counts.sessions],
                ["自由对话", health.data.counts.conversations],
                ["缺失 embedding", health.data.index.missing_embeddings],
                ["缺失 FTS", health.data.index.missing_fts],
              ]}
            />
          </>
        )}
      </PageState>

      <Section title="快捷入口">
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button component={RouterLink} to="/materials" variant="outlined">
            材料
          </Button>
          <Button component={RouterLink} to="/concepts" variant="outlined">
            概念
          </Button>
          <Button
            component={RouterLink}
            to="/session-questions"
            variant="outlined"
          >
            会话题
          </Button>
          <Button component={RouterLink} to="/tasks" variant="outlined">
            任务
          </Button>
          <Button
            component={RouterLink}
            to="/tasks/create/rebuild"
            variant="contained"
          >
            新建重建任务
          </Button>
          <Button component={RouterLink} to="/search" variant="outlined">
            全局搜索
          </Button>
        </Stack>
      </Section>

      <Section title="最近任务" count={tasks.data?.total}>
        <PageState
          loading={tasks.loading}
          error={tasks.error}
          empty={!tasks.data?.data?.length}
          emptyText="暂无任务；先提交一个重建任务试试。"
          onRetry={tasks.reload}
        >
          <Rows
            items={tasks.data?.data}
            render={(task: Task) => (
              <Card variant="outlined">
                <CardContent sx={{ py: 1.25, "&:last-child": { pb: 1.25 } }}>
                  <Typography>
                    <RouterLink to={`/tasks/${task.task_id}/show`}>
                      {task.task_id}
                    </RouterLink>{" "}
                    <Chip size="small" label={taskLabel(task.kind)} />{" "}
                    <Chip
                      size="small"
                      color={taskStatusColor(task.status)}
                      label={task.status}
                    />
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    创建 {formatDate(task.created_at)} · 结束{" "}
                    {formatDate(task.finished_at)}
                  </Typography>
                </CardContent>
              </Card>
            )}
          />
        </PageState>
      </Section>
    </Box>
  );
}
