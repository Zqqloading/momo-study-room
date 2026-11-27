import {
  ChipField,
  Datagrid,
  FunctionField,
  List,
  NumberField,
  SelectInput,
  TextField,
  TextInput,
} from "react-admin";
import { taskLabel } from "../api";

const materialFilters = [
  <TextInput key="q" source="q" label="搜索" alwaysOn />,
  <SelectInput
    key="status"
    source="status"
    label="状态"
    choices={[
      { id: "active", name: "active" },
      { id: "missing", name: "missing" },
    ]}
  />,
];

export function MaterialList() {
  return (
    <List
      exporter={false}
      filters={materialFilters}
      sort={{ field: "title", order: "ASC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="title" label="标题" />
        <TextField source="path" label="路径" />
        <NumberField source="version" label="版本" />
        <ChipField source="status" label="状态" />
        <TextField source="added_at" label="入库时间" />
      </Datagrid>
    </List>
  );
}

export function ConceptList() {
  return (
    <List
      exporter={false}
      filters={[
        <TextInput key="q" source="q" label="搜索" alwaysOn />,
        <SelectInput
          key="status"
          source="status"
          label="状态"
          choices={[
            { id: "active", name: "active" },
            { id: "proposed", name: "proposed" },
            { id: "known", name: "known" },
            { id: "skipped", name: "skipped" },
            { id: "orphaned", name: "orphaned" },
          ]}
        />,
      ]}
      sort={{ field: "mastery", order: "ASC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="name" label="概念" />
        <TextField source="id" label="ID" />
        <NumberField source="mastery" label="掌握度" />
        <TextField source="mastery_label" label="标签" />
        <ChipField source="status" label="状态" />
        <TextField source="review_due_at" label="复习到期" />
      </Datagrid>
    </List>
  );
}

export function BankQuestionList() {
  return (
    <List
      exporter={false}
      filters={[
        <TextInput key="q" source="q" label="搜索" alwaysOn />,
        <TextInput key="concept_id" source="concept_id" label="概念 ID" />,
        <SelectInput
          key="kind"
          source="kind"
          label="题型"
          choices={[
            { id: "recall", name: "recall" },
            { id: "discriminate", name: "discriminate" },
            { id: "apply", name: "apply" },
          ]}
        />,
      ]}
      sort={{ field: "id", order: "ASC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="id" label="题目 ID" />
        <TextField source="concept_id" label="概念" />
        <TextField source="kind" label="题型" />
        <TextField source="question_text" label="题干" />
      </Datagrid>
    </List>
  );
}

export function SessionQuestionList() {
  return (
    <List
      exporter={false}
      filters={[
        <TextInput key="q" source="q" label="搜索" alwaysOn />,
        <TextInput key="session_id" source="session_id" label="会话 ID" />,
        <TextInput key="concept_id" source="concept_id" label="概念 ID" />,
      ]}
      sort={{ field: "id", order: "DESC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="id" label="#" />
        <TextField source="session_id" label="会话" />
        <TextField source="concept_id" label="概念" />
        <TextField source="question_type" label="题型" />
        <TextField source="question_text" label="题干" />
        <NumberField source="score" label="分数" />
      </Datagrid>
    </List>
  );
}

export function SessionList() {
  return (
    <List
      exporter={false}
      filters={[
        <TextInput key="q" source="q" label="搜索" alwaysOn />,
        <SelectInput
          key="status"
          source="status"
          label="状态"
          choices={[
            { id: "active", name: "active" },
            { id: "finished", name: "finished" },
            { id: "abandoned", name: "abandoned" },
            { id: "completed", name: "completed" },
            { id: "partial", name: "partial" },
            { id: "unscored", name: "unscored" },
          ]}
        />,
        <SelectInput
          key="kind"
          source="kind"
          label="类型"
          choices={[
            { id: "daily", name: "daily" },
            { id: "review", name: "review" },
          ]}
        />,
      ]}
      sort={{ field: "date", order: "DESC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="date" label="日期" />
        <TextField source="kind" label="类型" />
        <TextField source="agent_status" label="运行态" />
        <TextField source="final_status" label="结算态" />
        <NumberField source="session_score" label="分数" />
        <NumberField source="question_count" label="题数" />
      </Datagrid>
    </List>
  );
}

export function ConversationList() {
  return (
    <List
      exporter={false}
      filters={[<TextInput key="q" source="q" label="搜索" alwaysOn />]}
      sort={{ field: "updated_at", order: "DESC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="title" label="标题" />
        <TextField source="updated_at" label="更新时间" />
        <NumberField source="message_count" label="消息数" />
      </Datagrid>
    </List>
  );
}

export function PipelineRunList() {
  return (
    <List
      exporter={false}
      filters={[
        <SelectInput
          key="kind"
          source="kind"
          label="类型"
          choices={[
            { id: "ingest", name: "ingest" },
            { id: "extract", name: "extract" },
            { id: "confirm", name: "confirm" },
            { id: "reindex", name: "reindex" },
          ]}
        />,
        <SelectInput
          key="status"
          source="status"
          label="状态"
          choices={[
            { id: "running", name: "running" },
            { id: "succeeded", name: "succeeded" },
            { id: "failed", name: "failed" },
            { id: "partial", name: "partial" },
          ]}
        />,
      ]}
      sort={{ field: "id", order: "DESC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="id" label="#" />
        <TextField source="kind" label="类型" />
        <ChipField source="status" label="状态" />
        <TextField source="started_at" label="开始" />
        <TextField source="finished_at" label="结束" />
        <TextField source="input" label="输入" />
        <TextField source="error" label="错误" />
      </Datagrid>
    </List>
  );
}

export function TaskList() {
  return (
    <List
      exporter={false}
      filters={[
        <SelectInput
          key="kind"
          source="kind"
          label="类型"
          choices={[
            { id: "ingest", name: "知识摄取" },
            { id: "rebuild", name: "知识重建" },
            { id: "evaluate", name: "整体评测" },
          ]}
        />,
        <SelectInput
          key="status"
          source="status"
          label="状态"
          choices={[
            { id: "queued", name: "queued" },
            { id: "running", name: "running" },
            { id: "succeeded", name: "succeeded" },
            { id: "failed", name: "failed" },
            { id: "awaiting_review", name: "awaiting_review" },
            { id: "cancelled", name: "cancelled" },
          ]}
        />,
      ]}
      sort={{ field: "created_at", order: "DESC" }}
    >
      <Datagrid bulkActionButtons={false} rowClick="show">
        <TextField source="task_id" label="任务号" />
        <FunctionField
          label="类型"
          render={(record: any) => taskLabel(record.kind)}
        />
        <ChipField source="status" label="状态" />
        <TextField source="created_at" label="创建" />
        <TextField source="finished_at" label="结束" />
      </Datagrid>
    </List>
  );
}
