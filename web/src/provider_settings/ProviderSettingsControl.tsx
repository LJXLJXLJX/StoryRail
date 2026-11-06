import { useRef, useState } from "react";
import { useEscapeDismiss } from "../DismissibleDialog";
import {
  providerSettingsApi,
  type ProviderPluginView,
  type ProviderSettingsView,
} from "../api";

import { SettingField, type SettingValue } from "./SettingField";

// 全局 Provider 设置：能力绑定与插件实例设置。项目与 Playground 共用，只影响之后新提交的任务；
// 字段按 Core 下发的 manifest widget 渲染，取值是否合法由 Core 校验。
// onChanged 在绑定或插件设置写成功后触发，供 Playground 等页面刷新能力列表。
export function ProviderSettingsControl({ onChanged }: { onChanged?: () => void }) {
  const [view, setView] = useState<ProviderSettingsView | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const details = useRef<HTMLDetailsElement>(null);
  useEscapeDismiss(details, () => {
    if (details.current) {
      details.current.open = false;
      details.current.querySelector("summary")?.focus();
    }
    setOpen(false);
  }, open);

  // 首次展开时才读取，避免每次进入页面都请求设置。
  function load(open: boolean) {
    if (!open || view !== null || pending) return;
    void apply(() => providerSettingsApi.read());
  }

  async function apply(
    action: () => Promise<ProviderSettingsView>,
    { notify = false }: { notify?: boolean } = {},
  ) {
    setPending(true);
    setError(null);
    try {
      setView(await action());
      if (notify) onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <details
      ref={details}
      className="provider-settings"
      title="只影响之后新提交的任务"
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
        load(event.currentTarget.open);
      }}
    >
      <summary aria-label="全局 Provider 设置">Provider 设置</summary>
      <div className="provider-settings-panel">
        {view === null ? (
          <p>{error ?? "正在读取 Provider 设置…"}</p>
        ) : (
          <fieldset disabled={pending}>
            <p className="provider-settings-note">
              项目与 Playground 共用；修改只影响之后新提交的任务，已有候选按提交时的设置保留。
            </p>
            <section aria-label="能力绑定">
              <h4>能力绑定</h4>
              {view.capabilities.map((capability) => (
                <label key={capability.id} className="provider-binding">
                  <span>{capability.label}</span>
                  {capability.candidates.length > 0 ? (
                    <select
                      aria-label={`${capability.label}插件`}
                      value={capability.bound_plugin_id ?? ""}
                      onChange={(event) =>
                        void apply(() => providerSettingsApi.bind(capability.id, event.target.value), { notify: true })
                      }
                    >
                      {capability.bound_plugin_id === null ? <option value="">未选择</option> : null}
                      {capability.candidates.map((candidate) => (
                        <option key={candidate.plugin_id} value={candidate.plugin_id}>
                          {candidate.label}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  {capability.message ? <small>{capability.message}</small> : null}
                </label>
              ))}
            </section>
            {view.plugins.map((plugin) => (
              <PluginSettings
                key={plugin.plugin_id}
                plugin={plugin}
                onChange={(settings) =>
                  void apply(() => providerSettingsApi.updatePlugin(plugin.plugin_id, settings), { notify: true })
                }
              />
            ))}
            <section aria-label="确定性工具">
              <h4>确定性工具</h4>
              <ul>
                {view.tools.map((tool) => (
                  <li key={tool.id}>
                    {tool.label} · {tool.available ? "可用" : "未配置"}
                  </li>
                ))}
              </ul>
            </section>
            {error ? <small className="provider-settings-error">{error}</small> : null}
          </fieldset>
        )}
      </div>
    </details>
  );
}

function PluginSettings({
  plugin,
  onChange,
}: {
  plugin: ProviderPluginView;
  onChange: (settings: Record<string, unknown>) => void;
}) {
  const fields = plugin.manifest.settings;
  return (
    <section aria-label={`${plugin.label} 设置`} className="provider-plugin">
      <h4>
        {plugin.label}
        {plugin.settings_summary ? <span> · {plugin.settings_summary}</span> : null}
      </h4>
      {plugin.endpoint ? <small>{plugin.endpoint}</small> : null}
      {plugin.settings_error ? <small className="provider-settings-error">{plugin.settings_error}</small> : null}
      {fields.map((field) => (
        <SettingField
          key={field.key}
          field={field}
          value={(plugin.settings[field.key] ?? null) as SettingValue}
          onChange={(value) => onChange({ ...plugin.settings, [field.key]: value })}
        />
      ))}
    </section>
  );
}
