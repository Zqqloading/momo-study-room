import polyglotI18nProvider from "ra-i18n-polyglot";
import chineseModule from "@haxqer/ra-language-chinese";

const messages = (chineseModule as any).default ?? chineseModule;

export const i18nProvider = polyglotI18nProvider(() => messages, "zh");
