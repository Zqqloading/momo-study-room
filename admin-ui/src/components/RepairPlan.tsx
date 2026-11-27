import {
  Box,
  Button,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { useNotify } from "react-admin";

export function RepairPlan({ repair }: { repair: any }) {
  const notify = useNotify();
  if (!repair) return null;

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      notify("已复制", { type: "info" });
    } catch {
      notify("复制失败，请手动选中", { type: "warning" });
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
      <Typography variant="h6">{repair.title || "修复计划"}</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        只读诊断；命令需要在终端执行。
      </Typography>
      {repair.preconditions?.length > 0 && (
        <Box
          component="ul"
          sx={{
            pl: 3,
            py: 1,
            my: 1,
            bgcolor: "action.hover",
            borderRadius: 1,
            typography: "body2",
          }}
        >
          {repair.preconditions.map((item: string) => (
            <li key={item}>{item}</li>
          ))}
        </Box>
      )}
      <Stack divider={<Divider flexItem />} spacing={1.5}>
        {(repair.steps || []).map((step: any, index: number) => (
          <Box key={`${step.title}-${index}`}>
            <Typography sx={{ fontWeight: 600 }}>
              {index + 1}. {step.title}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {step.why}
            </Typography>
            {step.precondition && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                前置：{step.precondition}
              </Typography>
            )}
            {step.command && (
              <Box
                sx={{
                  display: "flex",
                  gap: 1,
                  alignItems: "flex-start",
                  mt: 0.75,
                  p: 1,
                  bgcolor: "action.hover",
                  borderRadius: 1,
                }}
              >
                <Box
                  component="code"
                  sx={{
                    flex: 1,
                    fontSize: 12,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                  }}
                >
                  {step.command}
                </Box>
                <Button size="small" onClick={() => copy(step.command)}>
                  复制
                </Button>
              </Box>
            )}
            {step.path && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                路径：{step.path}
              </Typography>
            )}
            {step.skip_if && (
              <Typography variant="body2" color="warning.main" sx={{ mt: 0.5 }}>
                可跳过：{step.skip_if}
              </Typography>
            )}
          </Box>
        ))}
      </Stack>
      {repair.notes?.length > 0 && (
        <Box component="ul" sx={{ pl: 3, mt: 1.5, typography: "body2" }}>
          {repair.notes.map((item: string) => (
            <li key={item}>{item}</li>
          ))}
        </Box>
      )}
    </Paper>
  );
}
