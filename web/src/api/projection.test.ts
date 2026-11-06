import { expect, it } from "vitest";
import fixtures from "../test/story_reader_fixture.json";
import { parseStoryProjection } from "./projection";

const pages = [...Object.values(fixtures.projections), ...Object.values(fixtures.continuity.projections)];
const segmentPage = pages.find(page => page.level === "segment" && page.items.length > 0)!;

it("解析 Core 导出的各层故事事实和完整正文", () => {
  for (const page of pages) expect(parseStoryProjection(page)).toEqual(page);
  const preview = { ...segmentPage, text_mode: "preview", extensions: [] };
  expect(parseStoryProjection(preview)).toEqual(preview);
});

it("在渲染前拒绝未知字段和畸形嵌套事实", () => {
  const scenePage = parseStoryProjection(pages.find(page => page.level === "scene")!);
  const bad = [
    { ...segmentPage, undeclared: true },
    { ...segmentPage, script_revision: "1" },
    { ...segmentPage, revision: -1 },
    { ...segmentPage, text_preview_characters: false },
    { ...segmentPage, scope: { ...segmentPage.scope, extra: true } },
    { ...segmentPage, extensions: ["selection"] },
    { ...segmentPage, extensions: ["text", "text"] },
    { ...segmentPage, text_mode: "preview" },
    ...[
      { undeclared: true },
      { duration_estimate_seconds: "8" },
      { duration_estimate_seconds: Number.NaN },
      { parent: { kind: "shot", id: segmentPage.items[0].parent.id } },
      { provenance: { source: "project.json", field: {} } },
      { boundary_from_previous: { reason: "model_limit", continuity_instruction: {} } },
      { dialogue_lines: [{ character_id: "x", text: "对白", delivery: "轻声", extra: true }] },
    ].map(patch => ({ ...segmentPage, items: [{ ...segmentPage.items[0], ...patch }] })),
    { ...scenePage, items: [{ ...scenePage.items[0], shot_count: "2" }] },
    { ...scenePage, items: [{ ...scenePage.items[0], narration: [{
      ...scenePage.items[0].narration![0],
      en: { ...scenePage.items[0].narration![0].en, duration_seconds: {} },
    }] }] },
  ];
  for (const [index, page] of bad.entries()) {
    expect(() => parseStoryProjection(page), `畸形响应 ${index}`).toThrow();
  }
});

it('严格校验单 Shot 子节点过滤，拒绝跨父节点响应',()=>{
 const first=segmentPage.items[0];
 const page={...segmentPage,parent_id:first.parent.id,items:[first]};
 expect(parseStoryProjection(page).parent_id).toBe(first.parent.id);
 expect(()=>parseStoryProjection({...page,parent_id:'other-shot'})).toThrow();
 expect(()=>parseStoryProjection({...page,parent_id:null})).toThrow();
});
