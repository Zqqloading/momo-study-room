import type { ReactNode } from "react";
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
import { Link as RouterLink, useNavigate } from "react-router-dom";

export function PageState({
  loading,
  error,
  empty,
  emptyText = "暂无数据",
  onRetry,
  notFound,
  partial,
  stale,
  forbidden,
  children,
}: {
  loading?: boolean;
  error?: string | null;
  empty?: boolean;
  emptyText?: string;
  onRetry?: () => void;
  notFound?: boolean;
  partial?: boolean;
  stale?: boolean;
  forbidden?: boolean;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <Box sx={{ p: 4 }}>
        <Typography color="text.secondary">读取中…</Typography>
      </Box>
    );
  }
  if (forbidden) {
    return <Alert severity="error">没有权限访问该资源。</Alert>;
  }
  if (notFound ?? Boolean(error && /不存在|HTTP 404|404/.test(error))) {
    return (
      <Alert severity="warning">
        资源不存在{error ? `：${error}` : ""}。请从列表重新进入。
      </Alert>
    );
  }
  if (error) {
    return (
      <Alert
        severity="error"
        action={
          onRetry ? (
            <Button color="inherit" size="small" onClick={onRetry}>
              重试
            </Button>
          ) : undefined
        }
      >
        {error}
      </Alert>
    );
  }
  if (empty) {
    return (
      <Box sx={{ p: 4 }}>
        <Typography color="text.secondary">{emptyText}</Typography>
      </Box>
    );
  }
  return (
    <>
      {stale && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          数据可能不是最新：{stale}
        </Alert>
      )}
      {partial && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          部分区块读取失败；已显示可用数据。
        </Alert>
      )}
      {children}
    </>
  );
}

export function CountCards({ items }: { items: Array<[string, ReactNode]> }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
        gap: 1,
        my: 2,
      }}
    >
      {items.map(([label, value]) => (
        <Card key={label} variant="outlined">
          <CardContent sx={{ py: 1.25, "&:last-child": { pb: 1.25 } }}>
            <Typography variant="caption" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="h6">{value ?? "—"}</Typography>
          </CardContent>
        </Card>
      ))}
    </Box>
  );
}

export function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number | null;
  children: ReactNode;
}) {
  return (
    <Box component="section" sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>
        {title}
        {count !== undefined && count !== null ? `（${count}）` : ""}
      </Typography>
      {children}
    </Box>
  );
}

export function Rows({
  items,
  render,
  emptyText = "无",
}: {
  items?: any[];
  render: (item: any, index: number) => ReactNode;
  emptyText?: string;
}) {
  if (!items || items.length === 0) {
    return <Typography color="text.secondary">{emptyText}</Typography>;
  }
  return (
    <Stack divider={<Divider flexItem />} spacing={1}>
      {items.map((item, index) => (
        <Box key={item.id ?? item.session_id ?? index}>{render(item, index)}</Box>
      ))}
    </Stack>
  );
}

export function ProvenanceChip({ provenance }: { provenance?: any }) {
  if (!provenance) return null;
  const color =
    provenance.level === "chunk"
      ? "success"
      : provenance.level === "url"
        ? "info"
        : provenance.level === "concept"
          ? "warning"
          : "error";
  return (
    <Chip
      size="small"
      variant="outlined"
      color={color as any}
      label={provenance.label || provenance.level}
    />
  );
}

export function DetailLink({
  resource,
  id,
  label,
}: {
  resource: string;
  id: string | number;
  label?: ReactNode;
}) {
  return (
    <RouterLink to={`/${resource}/${encodeURIComponent(String(id))}/show`}>
      {label ?? id}
    </RouterLink>
  );
}

export function BackToList({
  resource,
  label,
}: {
  resource: string;
  label: string;
}) {
  const navigate = useNavigate();
  return (
    <Button
      size="small"
      sx={{ mb: 1 }}
      onClick={() => {
        if (window.history.length > 1) navigate(-1);
        else navigate(`/${resource}`);
      }}
    >
      ← {label}
    </Button>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Typography variant="body2" sx={{ mb: 0.5 }}>
      <strong>{label}：</strong>
      {children}
    </Typography>
  );
}
