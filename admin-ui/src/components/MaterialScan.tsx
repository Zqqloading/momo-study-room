import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { useNotify } from "react-admin";
import { apiPost } from "../api";
import { useApi } from "../hooks";

type ScanItem = {
  path: string;
  name: string;
  size: number;
  modified_at: string;
  material_id?: string;
  db_version?: number;
};

type ScanResult = {
  root: string;
  new: ScanItem[];
  changed: ScanItem[];
  unchanged: number;
  missing: Array<{
    id: string;
    title: string;
    path: string;
    version: number;
    status: string;
  }>;
  errors: Array<{ path: string; error: string }>;
};

export function MaterialScan() {
  const navigate = useNavigate();
  const notify = useNotify();
  const scan = useApi<ScanResult>("/materials/scan");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!scan.data) return;
    setSelected(new Set(scan.data.new.map((item) => item.path)));
  }, [scan.data]);

  const toggle = (path: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const submit = async () => {
    const paths = [...selected];
    if (paths.length === 0) return;
    setSubmitting(true);
    setError(null);
    const failures: string[] = [];
    let submitted = 0;
    for (const path of paths) {
      try {
        await apiPost("/tasks", {
          kind: "ingest",
          params: {
            path,
            dry_run: false,
            emit_chunks: true,
            extract: false,
          },
        });
        submitted += 1;
      } catch (err: any) {
        failures.push(`${path}: ${err.message}`);
      }
    }
    setSubmitting(false);
    if (failures.length > 0) {
      setError(failures.join("\n"));
    }
    notify(`已提交 ${submitted} 个摄取任务`, {
      type: failures.length > 0 ? "warning" : "info",
    });
    if (submitted > 0 && failures.length === 0) {
      navigate("/tasks");
    }
  };

  const data = scan.data;
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        spacing={1}
      >
        <Box>
          <Typography sx={{ fontWeight: 600 }}>扫描 materials/ 新增与变更</Typography>
          <Typography variant="body2" color="text.secondary">
            直接扫描磁盘，不需要逐个上传；新文件默认全选，变更文件默认不选。
          </Typography>
        </Box>
        <Button size="small" onClick={scan.reload} disabled={scan.loading}>
          重新扫描
        </Button>
      </Stack>

      {scan.loading && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          扫描中…
        </Typography>
      )}
      {scan.error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {scan.error}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mt: 1, whiteSpace: "pre-wrap" }}>
          {error}
        </Alert>
      )}

      {data && (
        <>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            <Chip color="info" label={`新增 ${data.new.length}`} />
            <Chip color="warning" label={`变更 ${data.changed.length}`} />
            <Chip label={`未变 ${data.unchanged}`} />
            <Chip
              color={data.missing.length > 0 ? "error" : "default"}
              label={`缺失 ${data.missing.length}`}
            />
          </Stack>

          {data.new.length > 0 && (
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="subtitle2">新增文件</Typography>
              <Stack divider={<Divider flexItem />}>
                {data.new.map((item) => (
                  <FormControlLabel
                    key={item.path}
                    control={
                      <Checkbox
                        checked={selected.has(item.path)}
                        onChange={() => toggle(item.path)}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2">{item.path}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {item.size} bytes · {item.modified_at}
                        </Typography>
                      </Box>
                    }
                  />
                ))}
              </Stack>
            </Box>
          )}

          {data.changed.length > 0 && (
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="subtitle2">
                已入库但内容变化（会 bump 版本）
              </Typography>
              <Stack divider={<Divider flexItem />}>
                {data.changed.map((item) => (
                  <FormControlLabel
                    key={item.path}
                    control={
                      <Checkbox
                        checked={selected.has(item.path)}
                        onChange={() => toggle(item.path)}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2">{item.path}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          当前 v{item.db_version} · {item.size} bytes ·{" "}
                          {item.modified_at}
                        </Typography>
                      </Box>
                    }
                  />
                ))}
              </Stack>
            </Box>
          )}

          {data.missing.length > 0 && (
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="subtitle2">库里有、磁盘缺失</Typography>
              {data.missing.map((item) => (
                <Typography
                  key={item.id}
                  variant="body2"
                  color="error"
                >
                  {item.path}（{item.id} · v{item.version} · {item.status}）
                </Typography>
              ))}
            </Box>
          )}

          {data.new.length === 0 &&
            data.changed.length === 0 &&
            data.missing.length === 0 && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                materials/ 下没有新增或变更文件。
              </Typography>
            )}

          {data.errors.length > 0 && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              {data.errors.length} 个文件读取失败；见接口 errors。
            </Alert>
          )}

          <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
            <Button
              variant="outlined"
              size="small"
              disabled={data.new.length === 0}
              onClick={() =>
                setSelected(new Set(data.new.map((item) => item.path)))
              }
            >
              全选新增
            </Button>
            <Button
              variant="contained"
              size="small"
              disabled={submitting || selected.size === 0}
              onClick={submit}
            >
              {submitting
                ? "提交中…"
                : `提交选中项摄取（${selected.size}）`}
            </Button>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
            批量提交使用默认参数：非 dry_run、emit_chunks、不 extract。
          </Typography>
        </>
      )}
    </Paper>
  );
}
