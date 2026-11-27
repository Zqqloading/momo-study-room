import { useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Stack,
  Typography,
} from "@mui/material";
import { apiUpload, UploadedFile } from "../api";

const ACCEPT = ".md,.html";

export function UploadZone({
  onUploaded,
  onSelect,
}: {
  onUploaded?: (paths: string[]) => void;
  onSelect?: (path: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<UploadedFile[]>([]);

  const upload = async (files: File[]) => {
    setError(null);
    if (files.length === 0) return;
    const invalid = files.filter(
      (file) => !/\.(md|html)$/i.test(file.name),
    );
    if (invalid.length > 0) {
      setError(
        `只支持 .md / .html：${invalid.map((file) => file.name).join("、")}`,
      );
      return;
    }
    setUploading(true);
    try {
      const result = await apiUpload(files);
      setUploaded(result.files);
      onUploaded?.(result.files.map((file) => file.path));
      if (result.files[0]) onSelect?.(result.files[0].path);
    } catch (err: any) {
      setError(err.message || "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Box>
      <Box
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void upload(Array.from(event.dataTransfer.files));
        }}
        sx={{
          p: 3,
          border: "2px dashed",
          borderColor: dragging ? "primary.main" : "divider",
          borderRadius: 2,
          bgcolor: dragging ? "action.hover" : "transparent",
          textAlign: "center",
          cursor: uploading ? "wait" : "pointer",
          transition: "border-color 120ms, background-color 120ms",
        }}
      >
        <Typography sx={{ fontWeight: 600 }}>
          {uploading ? "上传中…" : "拖拽 .md / .html 到这里，或点击选择"}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          保存到 materials/inbox/；同名文件不会被覆盖；单个文件上限 10MB。
        </Typography>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(event) => {
            void upload(Array.from(event.target.files || []));
            event.target.value = "";
          }}
        />
      </Box>

      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}

      {uploaded.length > 0 && (
        <Stack spacing={0.5} sx={{ mt: 1 }}>
          <Typography variant="body2" color="success.main">
            已上传 {uploaded.length} 个文件；确认下方路径后提交摄取。
          </Typography>
          {uploaded.map((file) => (
            <Stack
              key={file.path}
              direction="row"
              spacing={1}
              alignItems="center"
            >
              <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
                {file.path}
              </Typography>
              <Button
                size="small"
                onClick={() => onSelect?.(file.path)}
              >
                填入路径
              </Button>
            </Stack>
          ))}
        </Stack>
      )}
    </Box>
  );
}
