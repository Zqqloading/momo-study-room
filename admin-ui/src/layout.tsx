import {
  AppBar,
  Layout as RALayout,
  Menu,
  TitlePortal,
} from "react-admin";
import { Alert, Box, Button } from "@mui/material";
import { useLocation } from "react-router-dom";
import { useApi } from "./hooks";
import type { Health } from "./api";

const AppBarTitle = () => (
  <AppBar color="primary">
    <TitlePortal />
  </AppBar>
);

const GlobalBanner = () => {
  const location = useLocation();
  const { data } = useApi<Health>("/health");
  if (location.pathname === "/") return null;
  if (!data) return null;
  if (data.red.length === 0 && data.yellow.length === 0) return null;
  return (
    <Box sx={{ p: 1, pb: 0 }}>
      {data.red.map((item) => (
        <Alert key={item.code} severity="error" sx={{ mb: 0.5 }}>
          {item.message}
        </Alert>
      ))}
      {data.yellow.map((item) => (
        <Alert key={item.code} severity="warning" sx={{ mb: 0.5 }}>
          {item.message}
        </Alert>
      ))}
    </Box>
  );
};

const AppMenu = () => (
  <Box>
    <Menu>
      <Menu.DashboardItem />
      <Menu.Item to="/search" primaryText="全局搜索" />
      <Menu.ResourceItem name="sessions" />
      <Menu.ResourceItem name="conversations" />
      <Menu.ResourceItem name="materials" />
      <Menu.ResourceItem name="concepts" />
      <Menu.ResourceItem name="bank-questions" />
      <Menu.ResourceItem name="session-questions" />
      <Menu.ResourceItem name="pipeline-runs" />
      <Menu.ResourceItem name="tasks" />
      <Menu.Item to="/tasks/create/ingest" primaryText="新建摄取" />
      <Menu.Item to="/tasks/create/rebuild" primaryText="新建重建" />
      <Menu.Item to="/tasks/create/evaluate" primaryText="新建评测" />
    </Menu>
    <Box sx={{ p: 2, pt: 1 }}>
      <Button component="a" href="/" size="small" fullWidth>
        ← 返回学习界面
      </Button>
    </Box>
  </Box>
);

export const AppLayout = (props: any) => (
  <RALayout {...props} appBar={AppBarTitle} menu={AppMenu}>
    <GlobalBanner />
    {props.children}
  </RALayout>
);
