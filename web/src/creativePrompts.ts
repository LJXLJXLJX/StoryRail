import partnerTemplate from "./creative-partner-prompt.md?raw";
import convertTemplate from "./director-plan-convert-prompt.md?raw";
import directorPlanFormat from "./director-plan-format.md?raw";

// 两份提示词共用同一份最终交付格式，避免格式要求出现两个来源。
function withFormat(template: string): string {
  return template.replace("{{DIRECTOR_PLAN_FORMAT}}", directorPlanFormat.trim());
}

export const creativePartnerPrompt = withFormat(partnerTemplate);
export const directorPlanConvertPrompt = withFormat(convertTemplate);
