import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { useProtectedValue } from './draft_protection';
function Input({text}:{text:string}) {
 const draft=useProtectedValue(text);
 return <><input aria-label="草稿" value={draft.value} onChange={e=>draft.setValue(e.target.value)}/><button disabled={draft.conflict}>保存</button><button onClick={draft.reset}>取消</button>{draft.conflict?<p role="alert">并发冲突</p>:null}</>;
}
it('刷新干净输入；保护未保存输入；只有明确取消才接收并发版本',()=>{
 const view=render(<Input text="旧值"/>);
 view.rerender(<Input text="新值"/>);expect(screen.getByLabelText('草稿')).toHaveValue('新值');
 fireEvent.change(screen.getByLabelText('草稿'),{target:{value:'人工草稿'}});
 view.rerender(<Input text="外部更新"/>);
 expect(screen.getByLabelText('草稿')).toHaveValue('人工草稿');expect(screen.getByRole('button',{name:'保存'})).toBeDisabled();
 fireEvent.click(screen.getByRole('button',{name:'取消'}));expect(screen.getByLabelText('草稿')).toHaveValue('外部更新');
 expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('回调未返回保存结果时保留草稿，服务器接受相同值后解除冲突',()=>{
 const view=render(<Input text="旧值"/>);fireEvent.change(screen.getByLabelText('草稿'),{target:{value:'保存值'}});
 view.rerender(<Input text="旧值"/>);expect(screen.getByLabelText('草稿')).toHaveValue('保存值');
 view.rerender(<Input text="保存值"/>);expect(screen.getByRole('button',{name:'保存'})).toBeEnabled();
 view.rerender(<Input text="随后更新"/>);expect(screen.getByLabelText('草稿')).toHaveValue('随后更新');
});
