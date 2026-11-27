import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useNotify } from "react-admin";
import { apiPost, EVAL_SUITES } from "../api";
import { UploadZone } from "../components/UploadZone";
import { MaterialScan } from "../components/MaterialScan";


export function TaskCreatePage({ kind: fixedKind }: { kind?: string }) {
  const [kind, setKind] = useState(fixedKind || "rebuild");
  const [path, setPath] = useState("materials/");
  const [dryRun, setDryRun] = useState(false);
  const [extract, setExtract] = useState(false);
  const [emitChunks, setEmitChunks] = useState(true);
  const [ftsOnly, setFtsOnly] = useState(false);
  const [prune, setPrune] = useState(false);
  const [suites, setSuites] = useState<string[]>(["probe"]);
  const [mode, setMode] = useState("auto");
  const [questions, setQuestions] = useState("");
  const [labels, setLabels] = useState("");
  const [answers, setAnswers] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const notify = useNotify();

  useEffect(() => {
    if (fixedKind) setKind(fixedKind);
  }, [fixedKind]);

  const dirty =
    kind === "ingest"
      ? path !== "materials/" || dryRun || extract || !emitChunks
      : kind === "rebuild"
        ? ftsOnly || prune
        : suites.length !== 1 ||
          suites[0] !== "probe" ||
          mode !== "auto" ||
          Boolean(questions || labels || answers);

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const toggleSuite = (suite: string) => {
    setSuites((current) =>
      current.includes(suite)
        ? current.filter((item) => item !== suite)
        : [...current, suite],
    );
  };

  const submit = async () => {
    setError(null);
    if (kind === "ingest" && !path.trim()) {
      setError("path 不能为空");
      return;
    }
    if (kind === "ingest" && extract && !emitChunks) {
      setError("extract 需要 emit_chunks=true");
      return;
    }
    if (kind === "evaluate" && suites.length === 0) {
      setError("至少选择一个 suite");
      return;
    }
    if (kind === "evaluate" && mode === "real") {
      const confirmed = window.confirm(
        "real 模式会调用真实 provider，可能产生费用。继续？",
      );
      if (!confirmed) return;
    }

    const params: Record<string, any> =
      kind === "ingest"
        ? {
            path: path.trim(),
            dry_run: dryRun,
            emit_chunks: emitChunks,
            extract,
          }
        : kind === "rebuild"
          ? { fts_only: ftsOnly, prune }
          : {
              suites,
              mode,
              inputs: Object.fromEntries(
                Object.entries({ questions, labels, answers }).filter(
                  ([, value]) => value.trim(),
                ),
              ),
            };

    setSubmitting(true);
    try {
      const created = await apiPost<{ task_id: string; status: string }>(
        "/tasks",
        { kind, params },
      );
      notify("任务已提交", { type: "info" });
      navigate(`/tasks/${created.task_id}/show`, { replace: true });
    } catch (err: any) {
      setError(err.message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ p: 2, maxWidth: 760 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        新建任务
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        提交后只创建任务，不同步等待；到任务详情轮询状态。
      </Typography>
      <Alert severity="info" sx={{ mb: 2 }}>
        摄取任务最多跑到 extract，产出候选后停在 awaiting_review；确认仍走 CLI。
      </Alert>

      {!fixedKind && (
        <FormControl fullWidth sx={{ mb: 2 }}>
          <InputLabel>任务类型</InputLabel>
          <Select
            label="任务类型"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <MenuItem value="ingest">知识摄取</MenuItem>
            <MenuItem value="rebuild">知识重建</MenuItem>
            <MenuItem value="evaluate">整体评测</MenuItem>
          </Select>
        </FormControl>
      )}

      {kind === "ingest" && (
        <Stack spacing={1.5}>
          <MaterialScan />
          <UploadZone
            onUploaded={(paths) => {
              if (paths.length > 0) {
                notify(`已上传 ${paths.length} 个文件`, { type: "info" });
              }
            }}
            onSelect={setPath}
          />
          <TextField
            fullWidth
            label="材料路径"
            helperText="必须在 materials/ 下，后缀 .md 或 .html"
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={emitChunks}
                onChange={(event) => setEmitChunks(event.target.checked)}
              />
            }
            label="emit_chunks（产出 chunks.json）"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={extract}
                onChange={(event) => setExtract(event.target.checked)}
              />
            }
            label="extract（调用 LLM 抽取候选）"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={dryRun}
                onChange={(event) => setDryRun(event.target.checked)}
              />
            }
            label="dry_run（只预览，不写库）"
          />
        </Stack>
      )}

      {kind === "rebuild" && (
        <Stack spacing={1.5}>
          <FormControlLabel
            control={
              <Checkbox
                checked={ftsOnly}
                onChange={(event) => setFtsOnly(event.target.checked)}
              />
            }
            label="fts_only（只重建 FTS，不调 embedding）"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={prune}
                onChange={(event) => setPrune(event.target.checked)}
              />
            }
            label="prune（清理孤儿索引行）"
          />
        </Stack>
      )}

      {kind === "evaluate" && (
        <Stack spacing={1.5}>
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Suites
            </Typography>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {EVAL_SUITES.map((suite) => (
                <FormControlLabel
                  key={suite}
                  control={
                    <Checkbox
                      checked={suites.includes(suite)}
                      onChange={() => toggleSuite(suite)}
                    />
                  }
                  label={suite}
                />
              ))}
            </Stack>
          </Box>
          <FormControl fullWidth>
            <InputLabel>mode</InputLabel>
            <Select
              label="mode"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <MenuItem value="auto">auto</MenuItem>
              <MenuItem value="real">real</MenuItem>
              <MenuItem value="fake">fake</MenuItem>
            </Select>
          </FormControl>
          <TextField
            fullWidth
            label="questions.json（可选）"
            value={questions}
            onChange={(event) => setQuestions(event.target.value)}
          />
          <TextField
            fullWidth
            label="labels.json（可选）"
            value={labels}
            onChange={(event) => setLabels(event.target.value)}
          />
          <TextField
            fullWidth
            label="answers.json（可选）"
            value={answers}
            onChange={(event) => setAnswers(event.target.value)}
          />
        </Stack>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}
      <Button
        variant="contained"
        sx={{ mt: 2 }}
        disabled={submitting}
        onClick={submit}
      >
        {submitting ? "提交中…" : "提交任务"}
      </Button>
    </Box>
  );
}

export function TaskCreate() {
  return <TaskCreatePage />;
}
