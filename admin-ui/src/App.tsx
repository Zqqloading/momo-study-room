import { Admin, CustomRoutes, Resource } from "react-admin";
import { Route } from "react-router-dom";
import { dataProvider } from "./dataProvider";
import { i18nProvider } from "./i18n";
import { AppLayout } from "./layout";
import { Dashboard } from "./dashboard";
import { GlobalSearch } from "./pages/GlobalSearch";
import { TaskCreate, TaskCreatePage } from "./pages/TaskCreate";
import { TaskShow } from "./pages/TaskShow";
import {
  BankQuestionList,
  ConceptList,
  ConversationList,
  MaterialList,
  PipelineRunList,
  SessionList,
  SessionQuestionList,
  TaskList,
} from "./resources/lists";
import {
  BankQuestionShow,
  ConceptShow,
  ConversationShow,
  MaterialShow,
  PipelineRunShow,
  SessionQuestionShow,
  SessionShow,
} from "./resources/details";

export default function App() {
  return (
    <Admin
      dataProvider={dataProvider}
      dashboard={Dashboard}
      layout={AppLayout}
      i18nProvider={i18nProvider}
      title="内容影响面"
    >
      <Resource
        name="sessions"
        list={SessionList}
        show={SessionShow}
        options={{ label: "学习会话" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="conversations"
        list={ConversationList}
        show={ConversationShow}
        options={{ label: "自由对话" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="materials"
        list={MaterialList}
        show={MaterialShow}
        options={{ label: "材料" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="concepts"
        list={ConceptList}
        show={ConceptShow}
        options={{ label: "概念" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="bank-questions"
        list={BankQuestionList}
        show={BankQuestionShow}
        options={{ label: "题库题" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="session-questions"
        list={SessionQuestionList}
        show={SessionQuestionShow}
        options={{ label: "会话题" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="pipeline-runs"
        list={PipelineRunList}
        show={PipelineRunShow}
        options={{ label: "管线运行" }}
        hasCreate={false}
        hasEdit={false}
      />
      <Resource
        name="tasks"
        list={TaskList}
        show={TaskShow}
        create={TaskCreate}
        options={{ label: "任务" }}
        hasEdit={false}
      />
      <CustomRoutes>
        <Route path="/search" element={<GlobalSearch />} />
        <Route
          path="/tasks/create/ingest"
          element={<TaskCreatePage kind="ingest" />}
        />
        <Route
          path="/tasks/create/rebuild"
          element={<TaskCreatePage kind="rebuild" />}
        />
        <Route
          path="/tasks/create/evaluate"
          element={<TaskCreatePage kind="evaluate" />}
        />
      </CustomRoutes>
    </Admin>
  );
}
