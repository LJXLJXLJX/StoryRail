import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StoryNavigation } from "./StoryNavigation";
import type { Scene } from "../api";
import { parseStoryProjection } from "../api/projection";
import fixture from "../test/story_reader_fixture.json";
const scenes = fixture.continuity.production_snapshot.director_script.scenes as Scene[];
afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); });
it("三级导航始终展开并保留真实身份与键盘定位", () => {
  const onChoose = vi.fn();
  const s=scenes[1], h=s.shots[1], g=h.segments[0];
  render(<StoryNavigation title="潮汐" scenes={scenes} target={{level:'segment',sceneId:s.id,id:g.id}} timingConfirmed onChoose={onChoose}><p>当前片段正文</p></StoryNavigation>);
  const nav=screen.getByRole('navigation',{name:'故事层级'});
  const tree=within(nav).getByRole('region',{name:'场景、镜头与片段树'});
  expect(within(tree).getByRole('button',{current:'page'})).toHaveTextContent('连续推进的前半程');
  expect(within(tree).getAllByRole('button',{name:/场景 \d/})).toHaveLength(scenes.length);
  expect(within(tree).getAllByRole('button',{name:/镜头 \d/})).toHaveLength(scenes.flatMap((item)=>item.shots).length);
  expect(within(tree).getAllByRole('button',{name:/片段 \d/})).toHaveLength(scenes.flatMap((item)=>item.shots).flatMap((item)=>item.segments).length);
  expect(within(tree).getByRole('button',{name:/场景 2.*22 秒/})).toBeVisible();
  expect(within(tree).getByRole('button',{name:/镜头 2.*16 秒/})).toBeVisible();
  expect(within(tree).getAllByText('8 秒').length).toBeGreaterThan(0);
  const otherShotSegments=within(tree).getByRole('list',{name:'场景 2－镜头 1 的生成片段'});
  expect(within(otherShotSegments).getByRole('button',{name:/小满抬头看向站牌/})).toBeVisible();
  fireEvent.click(within(otherShotSegments).getByRole('button',{name:/小满抬头看向站牌/}));
  expect(onChoose).toHaveBeenLastCalledWith({level:'segment',sceneId:s.id,id:s.shots[0].segments[0].id});
  expect(screen.queryByRole('button',{name:/返回上一级/})).not.toBeInTheDocument();
  const sceneTwoShots=within(tree).getByRole('list',{name:'场景 2 的连续镜头'});
  const row=within(sceneTwoShots).getByRole('button',{name:/镜头 1/});row.focus();fireEvent.keyDown(row,{key:'End'});
  expect(within(tree).getAllByRole('button').at(-1)).toHaveFocus();
  const sceneButton=within(tree).getByRole('button',{name:new RegExp(`场景 2.*${s.title}`)});
  fireEvent.click(sceneButton);
  expect(onChoose).toHaveBeenLastCalledWith({level:'scene',sceneId:s.id,id:s.id});
});
it("拒绝非法 DTO，移动端导航开关不复制内容",()=>{
  expect(()=>parseStoryProjection({items:[]})).toThrow();
  const onChoose=vi.fn();
  render(<StoryNavigation title="潮汐" scenes={scenes} target={null} timingConfirmed={false} onChoose={onChoose}><p>唯一正文</p></StoryNavigation>);
  const tree=screen.getByRole('region',{name:'场景、镜头与片段树'});
  expect(within(tree).getAllByRole('button',{name:/镜头 \d/})).toHaveLength(scenes.flatMap((item)=>item.shots).length);
  const sceneTwoShots=within(tree).getByRole('list',{name:'场景 2 的连续镜头'});
  fireEvent.click(within(sceneTwoShots).getByRole('button',{name:/同一镜头连续观察环境/}));
  expect(onChoose).toHaveBeenLastCalledWith({level:'shot',sceneId:scenes[1].id,id:scenes[1].shots[1].id});
  expect(within(tree).getAllByText('N/A')).toHaveLength(
    scenes.length + scenes.flatMap((item)=>item.shots).length + scenes.flatMap((item)=>item.shots).flatMap((item)=>item.segments).length,
  );
  fireEvent.click(screen.getByRole('button',{name:'故事位置'}));
  expect(screen.getAllByText('唯一正文')).toHaveLength(1);
});
