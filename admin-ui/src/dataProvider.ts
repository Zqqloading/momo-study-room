import type { DataProvider } from "react-admin";
import { apiGet, apiPost } from "./api";

const SLUGS: Record<string, string> = {
  materials: "materials",
  concepts: "concepts",
  "bank-questions": "bank-questions",
  "session-questions": "session-questions",
  sessions: "sessions",
  conversations: "conversations",
  "pipeline-runs": "pipeline-runs",
  tasks: "tasks",
};

function withId(resource: string, record: any): any {
  if (!record) return record;
  if (record.id !== undefined) return record;
  if (resource === "sessions" && record.session_id) {
    return { ...record, id: record.session_id };
  }
  if (resource === "tasks" && record.task_id) {
    return { ...record, id: record.task_id };
  }
  return record;
}

async function getOne(resource: string, id: string | number): Promise<any> {
  const key = encodeURIComponent(String(id));
  let path = "";
  if (resource === "materials") path = `/material/${key}`;
  else if (resource === "concepts") path = `/concept/${key}`;
  else if (resource === "bank-questions") path = `/question?bank_id=${key}`;
  else if (resource === "session-questions")
    path = `/question?session_question_id=${key}`;
  else if (resource === "sessions") path = `/session/${key}`;
  else if (resource === "conversations") path = `/conversation/${key}`;
  else if (resource === "pipeline-runs") path = `/pipeline-runs/${key}`;
  else if (resource === "tasks") path = `/tasks/${key}`;
  else throw new Error(`未知资源：${resource}`);

  const payload = await apiGet<any>(path);
  if (resource === "materials") {
    return { ...payload, id: payload.material.id };
  }
  if (resource === "concepts") {
    return { ...payload, id: payload.concept.id };
  }
  if (resource === "bank-questions" || resource === "session-questions") {
    return { ...payload, id: payload.question.id };
  }
  if (resource === "sessions") {
    return { ...payload, id: payload.session.session_id };
  }
  if (resource === "conversations") {
    return { ...payload, id: payload.conversation.id };
  }
  return withId(resource, payload);
}

export const dataProvider: DataProvider = {
  async getList(resource, params) {
    const slug = SLUGS[resource];
    if (!slug) throw new Error(`未知资源：${resource}`);
    const search = new URLSearchParams();
    const pagination = params.pagination ?? { page: 1, perPage: 25 };
    search.set("page", String(pagination.page));
    search.set("per_page", String(pagination.perPage));
    if (params.sort?.field) {
      search.set("sort", String(params.sort.field));
      search.set("order", String(params.sort.order || "asc").toLowerCase());
    }
    for (const [key, value] of Object.entries(params.filter || {})) {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    }
    const payload = await apiGet<any>(`/${slug}?${search.toString()}`);
    return {
      data: (payload.data || []).map((record: any) => withId(resource, record)),
      total: payload.total || 0,
    };
  },

  async getOne(resource, params) {
    return { data: await getOne(resource, params.id) };
  },

  async getMany(resource, params) {
    const slug = SLUGS[resource];
    if (!slug) throw new Error(`未知资源：${resource}`);
    if (params.ids.length === 0) return { data: [] };
    const search = new URLSearchParams({
      ids: params.ids.map(String).join(","),
    });
    const payload = await apiGet<any>(`/${slug}?${search.toString()}`);
    return {
      data: (payload.data || []).map((record: any) =>
        withId(resource, record),
      ),
    };
  },

  async getManyReference(resource, params) {
    return this.getList(resource, {
      pagination: { page: 1, perPage: 100 },
      sort: params.sort,
      filter: { ...params.filter, [params.target]: params.id },
      meta: params.meta,
    });
  },

  async create(resource, params) {
    if (resource !== "tasks") {
      throw new Error("当前后台只允许创建任务");
    }
    const kind = params.data.kind;
    const taskParams = params.data.params || {};
    const created = await apiPost<{ task_id: string; status: string }>(
      "/tasks",
      { kind, params: taskParams },
    );
    return {
      data: {
        id: created.task_id,
        task_id: created.task_id,
        kind,
        params: taskParams,
        status: created.status,
      },
    } as any;
  },

  async update() {
    throw new Error("当前后台只读；写操作请提交任务");
  },

  async updateMany() {
    throw new Error("当前后台只读；写操作请提交任务");
  },

  async delete() {
    throw new Error("当前后台只读；写操作请提交任务");
  },

  async deleteMany() {
    throw new Error("当前后台只读；写操作请提交任务");
  },
};
