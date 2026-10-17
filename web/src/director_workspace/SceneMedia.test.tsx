import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { SceneMedia } from './SceneMedia';
import type { WorkspaceFlatProps } from './contracts';
import type { Scene } from '../api';
import fixture from '../test/story_reader_fixture.json';
it('Scene 成片只展示最新结果，并提供删除与双音量滑块',()=>{
 const snapshot=structuredClone(fixture.continuity.production_snapshot) as unknown as WorkspaceFlatProps['snapshot'];
 const scene=structuredClone(snapshot.director_script!.scenes[0]) as Scene;
 scene.scene_final={provider_available:true,reason:"已就绪。",ready:true,
  zh:{active_generation_id:null,latest_succeeded_generation_id:'a'.repeat(32),current_asset_id:'b'.repeat(32),outdated:false},
  en:{active_generation_id:null,latest_succeeded_generation_id:null,current_asset_id:null,outdated:false}};
 scene.animatic=undefined;
 snapshot.allowed_actions=['generate_scene_final'];
 snapshot.assets.push({id:'b'.repeat(32),media_type:'video/mp4',image_category:null,byte_count:20,duration_seconds:2,content_url:'/fixture.mp4',is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false,allowed_actions:[]});
 const base=snapshot.generations[0];
 snapshot.generations=[{...base,id:'a'.repeat(32),kind:'scene_final_video',language:'zh',target_id:scene.id,phase:'succeeded',output_asset_id:'b'.repeat(32),allowed_actions:['dismiss_history']}, {...base,id:'c'.repeat(32),kind:'scene_final_video',language:'en',target_id:scene.id,phase:'failed',output_asset_id:null,message:'合成故障',allowed_actions:['dismiss_history']}];
 const generate=vi.fn();
 const dismiss=vi.fn();
 const props={snapshot,busy:false,onGenerateSceneFinal:generate,onDismissGeneration:dismiss} as unknown as WorkspaceFlatProps;
 const view=render(<SceneMedia {...props} scene={scene}/>);
 // 中文成片成功、英文失败：各自展示在对应语言区块里。
 expect(screen.getByRole('alert')).toHaveTextContent('英文 Scene 成片 合成失败');
 expect(screen.getByRole('alert')).toHaveTextContent('合成故障');
 const previews=[...document.querySelectorAll('video')];
 expect(previews[0]).toHaveAttribute('src','/fixture.mp4');
 expect(previews).toHaveLength(1);
 for(const preview of previews){expect(preview).toHaveClass('scene-final-preview');expect(preview).toHaveAttribute('data-aspect-ratio','16:9');}
 expect(screen.getByRole('slider',{name:'视频自带音频音量'})).toBeInTheDocument();
 expect(screen.getByRole('slider',{name:'旁白音频音量'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'删除当前中文 Scene 成片'}));
 expect(dismiss).toHaveBeenCalledExactlyOnceWith('a'.repeat(32));
 fireEvent.click(screen.getByRole('button',{name:'重新生成 Scene 成片'}));expect(generate).toHaveBeenCalledExactlyOnceWith(scene.id,1,1);
 view.rerender(<SceneMedia {...props} snapshot={{...snapshot,allowed_actions:[]}} scene={scene}/>);
 expect(screen.getByRole('button',{name:'重新生成 Scene 成片'})).toBeDisabled();
});

it('Animatic 只展示当前结果，并提供删除按钮而不展开历史',()=>{
 const snapshot=structuredClone(fixture.continuity.production_snapshot) as unknown as WorkspaceFlatProps['snapshot'];
 const scene=structuredClone(snapshot.director_script!.scenes[0]) as Scene;
 scene.scene_final=undefined;
 scene.animatic={provider_available:true,reason:"已就绪。",ready:true,active_generation_id:null,latest_succeeded_generation_id:'a'.repeat(32)};
 snapshot.allowed_actions=['generate_scene_animatic'];
 snapshot.assets.push({id:'b'.repeat(32),media_type:'video/mp4',image_category:null,byte_count:20,duration_seconds:2,content_url:'/animatic.mp4',is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false,allowed_actions:[]});
 const base=snapshot.generations[0];
 snapshot.generations=[{...base,id:'a'.repeat(32),kind:'scene_animatic',language:null,target_id:scene.id,phase:'succeeded',output_asset_id:'b'.repeat(32),allowed_actions:['dismiss_history']}];
 const generate=vi.fn();
 const dismiss=vi.fn();
 render(<SceneMedia {...({snapshot,busy:false,onGenerateSceneAnimatic:generate,onDismissGeneration:dismiss} as unknown as WorkspaceFlatProps)} scene={scene}/>);
 expect(screen.getByRole('heading',{name:'Animatic'})).toBeInTheDocument();
 expect(document.querySelectorAll('video')).toHaveLength(1);
 expect(document.querySelector('video')).toHaveAttribute('src','/animatic.mp4');
 expect(screen.queryByText(/查看 Animatic 历史版本/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'删除当前 Animatic'}));
 expect(dismiss).toHaveBeenCalledExactlyOnceWith('a'.repeat(32));
});

it('Scene 成片过期时提示最终装配会拒绝它',()=>{
 const snapshot=structuredClone(fixture.continuity.production_snapshot) as unknown as WorkspaceFlatProps['snapshot'];
 const scene=structuredClone(snapshot.director_script!.scenes[0]) as Scene;
 scene.scene_final={provider_available:true,reason:"已就绪。",ready:true,
  zh:{active_generation_id:null,latest_succeeded_generation_id:'a'.repeat(32),current_asset_id:null,outdated:true},
  en:{active_generation_id:null,latest_succeeded_generation_id:null,current_asset_id:null,outdated:false}};
 scene.animatic=undefined;
 snapshot.allowed_actions=['generate_scene_final'];
 snapshot.assets.push({id:'b'.repeat(32),media_type:'video/mp4',image_category:null,byte_count:20,duration_seconds:2,content_url:'/fixture.mp4',is_in_use: false, usage_reasons: [], retains_derived_assets_on_delete: false,allowed_actions:[]});
 const base=snapshot.generations[0];
 snapshot.generations=[{...base,id:'a'.repeat(32),kind:'scene_final_video',language:'zh',target_id:scene.id,phase:'succeeded',output_asset_id:'b'.repeat(32),allowed_actions:['dismiss_history']}];
 render(<SceneMedia {...({snapshot,busy:false,onGenerateSceneFinal:vi.fn(),onDismissGeneration:vi.fn()} as unknown as WorkspaceFlatProps)} scene={scene}/>);
 expect(screen.getByRole('status')).toHaveTextContent('中文 Scene 成片已落后');
 expect(screen.getByRole('status')).toHaveTextContent('最终装配会拒绝它');
});
