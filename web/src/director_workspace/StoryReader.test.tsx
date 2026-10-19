import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StoryNavigation } from "./StoryNavigation";
import type { Scene } from "../api";
import { parseStoryProjection } from "../api/projection";
import fixture from "../test/story_reader_fixture.json";
const scenes = fixture.continuity.production_snapshot.director_script.scenes as Scene[];
afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
it("场景与片段导航始终展开并保留真实身份与键盘定位", () => {
  const onChoose = vi.fn();
  const s=scenes[1], g=s.segments.find((item)=>item.shot_ids[0]===s.shots[1].id)!;
  render(<StoryNavigation title="潮汐" scenes={scenes} target={{level:'segment',sceneId:s.id,id:g.id}} timingConfirmed onChoose={onChoose}><p>当前片段正文</p></StoryNavigation>);
  const nav=screen.getByRole('navigation',{name:'故事层级'});
  const tree=within(nav).getByRole('region',{name:'场景与片段树'});
  expect(within(tree).getByRole('button',{current:'page'})).toHaveTextContent('连续推进的前半程');
  expect(within(tree).getAllByRole('button',{name:/场景 \d/})).toHaveLength(scenes.length);
  expect(within(tree).getAllByRole('button',{name:/片段 \d/})).toHaveLength(scenes.flatMap((item)=>item.segments).length);
  expect(within(tree).getByRole('button',{name:/场景 2.*22 秒/})).toBeVisible();
  expect(within(tree).getAllByText('8 秒').length).toBeGreaterThan(0);
  const sceneTwoSegments=within(tree).getByRole('list',{name:'场景 2 的生成片段'});
  expect(within(sceneTwoSegments).getByRole('button',{name:/小满抬头看向站牌/})).toBeVisible();
  fireEvent.click(within(sceneTwoSegments).getByRole('button',{name:/小满抬头看向站牌/}));
  expect(onChoose).toHaveBeenLastCalledWith({level:'segment',sceneId:s.id,id:s.segments[0].id});
  expect(screen.queryByRole('button',{name:/返回上一级/})).not.toBeInTheDocument();
  const row=within(sceneTwoSegments).getAllByRole('button')[0];row.focus();fireEvent.keyDown(row,{key:'End'});
  expect(within(tree).getAllByRole('button').at(-1)).toHaveFocus();
  const sceneButton=within(tree).getByRole('button',{name:new RegExp(`场景 2.*${s.title}`)});
  fireEvent.click(sceneButton);
  expect(onChoose).toHaveBeenLastCalledWith({level:'scene',sceneId:s.id,id:s.id});
});
it("拒绝非法 DTO，移动端导航开关不复制内容",()=>{
  expect(()=>parseStoryProjection({items:[]})).toThrow();
  const onChoose=vi.fn();
  render(<StoryNavigation title="潮汐" scenes={scenes} target={null} timingConfirmed={false} onChoose={onChoose}><p>唯一正文</p></StoryNavigation>);
  const tree=screen.getByRole('region',{name:'场景与片段树'});
  expect(within(tree).getAllByText('N/A')).toHaveLength(
    scenes.length + scenes.flatMap((item)=>item.segments).length,
  );
  fireEvent.click(screen.getByRole('button',{name:'故事位置'}));
  expect(screen.getAllByText('唯一正文')).toHaveLength(1);
});
it("片段标签显示段内切镜与长镜头续段",()=>{
  const base=scenes[1];
  const shots=[0,1,2].map((i)=>({...base.shots[0],id:String(i).repeat(32),action:`镜头动作 ${i+1}`}));
  const segment=(id:string,shotIds:string[],action:string,continues:boolean)=>({
    ...base.segments[0],id:id.repeat(32),shot_ids:shotIds,action,
    boundary_from_previous:continues?{reason:'continuity_anchor' as const,continuity_instruction:'延续。'}:null,
  });
  const scene:Scene={...base,shots,segments:[
    segment('a',[shots[0].id,shots[1].id],'正反打',false),
    segment('b',[shots[2].id],'长镜头前段',false),
    segment('c',[shots[2].id],'长镜头后段',true),
  ]};
  render(<StoryNavigation title="潮汐" scenes={[scene]} target={null} timingConfirmed onChoose={vi.fn()}><p>正文</p></StoryNavigation>);
  const list=screen.getByRole('list',{name:'场景 1 的生成片段'});
  expect(within(list).getByRole('button',{name:/片段 1 · 镜头 1–2.*正反打/})).toBeVisible();
  expect(within(list).getByRole('button',{name:/片段 2 · 镜头 3 .*长镜头前段|片段 2 · 镜头 3长镜头前段/})).toBeVisible();
  expect(within(list).getByRole('button',{name:/片段 3 · 镜头 3（续）.*长镜头后段/})).toBeVisible();
});

it("片段行显示服务端提供的 15 秒软约束与对白时长提示", () => {
  const base = scenes[1];
  const scene: Scene = structuredClone(base);
  scene.segments[0].duration_estimate_seconds = 16;
  const warning = {
    segment_id: scene.segments[1].id,
    estimated_seconds: 9.5,
    duration_seconds: scene.segments[1].duration_estimate_seconds,
  };
  render(
    <StoryNavigation
      title="潮汐"
      scenes={[scene]}
      target={null}
      timingConfirmed
      timingWarnings={[warning]}
      softDurationLimits={{ [scene.segments[0].id]: 15 }}
      onChoose={vi.fn()}
    >
      <p>正文</p>
    </StoryNavigation>,
  );
  const rows = within(
    screen.getByRole("list", { name: "场景 1 的生成片段" }),
  ).getAllByRole("button");
  expect(rows[0]).toHaveTextContent("超过 15 秒软约束");
  expect(within(rows[0]).getByText("超过 15 秒软约束")).toHaveClass(
    "is-video-duration",
  );
  expect(rows[0]).toHaveTextContent("16 秒");
  expect(rows[1]).toHaveTextContent("对白约需 9.5 秒，超过预估时长");
  expect(
    within(rows[1]).getByText("对白约需 9.5 秒，超过预估时长"),
  ).toHaveClass("is-dialogue-duration");
  expect(rows[2]).not.toHaveTextContent(/软约束|对白约需/);
  // 共享边界 Shot 的“（续）”标签保持不变。
  expect(rows[2]).toHaveTextContent("镜头 2（续）");
});

it("片段行显示对白 TTS 与视频待生成项目", () => {
  const base = scenes[1];
  render(
    <StoryNavigation
      title="潮汐"
      scenes={[base]}
      target={null}
      timingConfirmed
      pendingGenerationItems={{
        [base.segments[0].id]: ["对白 TTS", "视频"],
        [base.segments[1].id]: ["视频"],
        [base.segments[2].id]: [],
      }}
      onChoose={vi.fn()}
    >
      <p>正文</p>
    </StoryNavigation>,
  );
  const rows = within(
    screen.getByRole("list", { name: "场景 1 的生成片段" }),
  ).getAllByRole("button");
  expect(rows[0]).toHaveTextContent("待生成项目：对白 TTS、视频");
  expect(within(rows[0]).getByText("对白 TTS")).toHaveClass(
    "is-dialogue-tts",
  );
  expect(within(rows[0]).getByText("视频")).toHaveClass("is-video");
  expect(rows[1]).toHaveTextContent("待生成项目：视频");
  expect(rows[2]).not.toHaveTextContent("待生成项目");
});
