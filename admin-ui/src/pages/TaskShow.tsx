import { useParams, Link as RouterLink } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import { useTaskPolling } from "../hooks";
import { formatDate, taskLabel, taskStatusColor } from "../api";
import {
  BackToList,
  CountCards,
  DetailLink,
  Rows,
  Section,
} from "../components/common";

function StatusChip({ status }: { status: string }) {
  return <Chip color={taskStatusColor(status)} label={status} />;
}

export function TaskShow() {
  const { id } = useParams();
  const { task, error, reload } = useTaskPolling(id);
  if (!task && !error) {
    return <Typography sx={{ p: 3 }}>读取中…</Typography>;
  }
  if (error && !task) {
    return (
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={reload}>
            重试
          </Button>
        }
      >
        {error}
      </Alert>
    );
  }
  if (!task) return null;

  return (
    <Box sx={{ p: 2 }}>
      <BackToList resource="tasks" label="任务列表" />
      <Typography variant="overline" color="text.secondary">
        {taskLabel(task.kind)}
      </Typography>
      <Typography variant="h4" sx={{ mb: 1 }}>
        任务 {task.task_id}
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <StatusChip status={task.status} />
        <Chip variant="outlined" label={`创建 ${formatDate(task.created_at)}`} />
        <Chip variant="outlined" label={`开始 ${formatDate(task.started_at)}`} />
        <Chip variant="outlined" label={`结束 ${formatDate(task.finished_at)}`} />
      </Stack>

      {error && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          {error}
          <Button size="small" onClick={reload} sx={{ ml: 1 }}>
            手动刷新
          </Button>
        </Alert>
      )}
      {task.error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {task.error}
        </Alert>
      )}

      <Section title="进度">
        <Card variant="outlined">
          <CardContent>
            <Typography>
              {task.progress?.phase || "等待执行"}
              {task.progress?.current != null
                ? ` · ${task.progress.current}/${task.progress.total ?? "?"}`
                : ""}
            </Typography>
            {task.progress?.message && (
              <Typography variant="body2" color="text.secondary">
                {task.progress.message}
              </Typography>
            )}
          </CardContent>
        </Card>
      </Section>

      {task.log_tail?.length > 0 && (
        <Section title="日志尾">
          <Box
            component="pre"
            sx={{
              p: 1.5,
              bgcolor: "action.hover",
              borderRadius: 1,
              fontSize: 12,
              overflow: "auto",
              maxHeight: 320,
            }}
          >
            {task.log_tail.join("\n")}
          </Box>
        </Section>
      )}

      {task.result && (
        <Section title="结果">
          {task.kind === "ingest" && (
            <>
              <CountCards
                items={[
                  ["材料", task.result.material_id || "—"],
                  ["版本", task.result.version ?? "—"],
                  ["父块", task.result.chunks_parent ?? "—"],
                  ["子块", task.result.chunks_child ?? "—"],
                  ["候选", task.result.candidates ?? "—"],
                  ["抽取失败", task.result.extract_failures ?? "—"],
                ]}
              />
              {task.result.material_id && (
                <Typography>
                  材料详情：{" "}
                  <DetailLink
                    resource="materials"
                    id={task.result.material_id}
                    label={task.result.material_id}
                  />
                </Typography>
              )}
              {task.result.candidates_path && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  候选文件：{task.result.candidates_path}（确认仍走 CLI）
                </Typography>
              )}
            </>
          )}
          {task.kind === "rebuild" && (
            <CountCards
              items={[
                ["FTS 行", task.result.fts_rows ?? "—"],
                ["补齐 embedding", task.result.embedded ?? "—"],
                ["补前缺失", task.result.missing_before ?? "—"],
              ]}
            />
          )}
          {task.kind === "evaluate" && (
            <>
              <Chip
                color={task.result.passed ? "success" : "error"}
                label={task.result.passed ? "整体通过" : "未通过"}
                sx={{ mb: 1 }}
              />
              <Rows
                items={task.result.items || []}
                render={(item: any) => (
                  <Typography>
                    <Chip
                      size="small"
                      color={
                        item.status === "skipped"
                          ? "default"
                          : item.passed
                            ? "success"
                            : "error"
                      }
                      label={item.status}
                    />{" "}
                    <strong>{item.name}</strong>{" "}
                    {item.reason ? `· ${item.reason}` : ""}
                    {item.report ? (
                      <Typography variant="body2" color="text.secondary">
                        报告：{item.report}
                      </Typography>
                    ) : null}
                  </Typography>
                )}
              />
            </>
          )}
          <Divider sx={{ my: 1 }} />
          <Box
            component="pre"
            sx={{ fontSize: 11, overflow: "auto", color: "text.secondary" }}
          >
            {JSON.stringify(task.result, null, 2)}
          </Box>
        </Section>
      )}

      <Section title="操作">
        <Stack direction="row" spacing={1}>
          <Button component={RouterLink} to="/tasks" variant="outlined">
            返回任务列表
          </Button>
          {task.kind === "rebuild" && task.status === "succeeded" && (
            <Button component={RouterLink} to="/" variant="outlined">
              查看总览
            </Button>
          )}
        </Stack>
      </Section>
    </Box>
  );
}
