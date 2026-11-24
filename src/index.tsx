import {
  ButtonItem,
  Field,
  Navigation,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaImage } from "react-icons/fa";

type Mode = "launch" | "splash";
type Info = { launcher: string; apps: Record<string, { mode?: Mode }> };
type Shortcut = { appid: number; name: string; options: string };

const getInfo = callable<[], Info>("get_info");
const wowShortcuts = callable<[shortcuts: { appid: number; exe: string; startdir: string }[]], number[]>(
  "wow_shortcuts",
);
const dropOldLauncher = callable<[], boolean>("drop_old_launcher");
const setMode = callable<[appid: number, mode: Mode], Info["apps"]>("set_mode");
const closeSplash = callable<[], number>("close_splash");
const bugReport = callable<[], Record<string, any>>("bug_report");

// GitHub repo that "Report a problem" opens a new issue on.
const REPO = "AstroPhyzix/wow-splash";
const MAX_URL = 7500; // GitHub rejects much longer new-issue links

declare const appStore: any;

const SHORTCUT = 1073741824; // app_type of non-Steam shortcuts
// Our wrapper in launch options: "<...>/wow-splash/launch.sh" <appid> (older versions used a
// longer folder name, also matched so they can be moved over)
const WRAPPER = /"[^"]*\/[\w-]*wow-splash\/launch\.sh"\s+\d+\s+/g;
const OLD_PATH = /\/[\w-]+-wow-splash\/launch\.sh/;

function shortcuts(): { appid: number; name: string }[] {
  return (appStore?.allApps ?? [])
    .filter((a: any) => a.app_type === SHORTCUT)
    .map((a: any) => ({ appid: a.appid, name: a.display_name }))
    .sort((a: any, b: any) => a.name.localeCompare(b.name));
}

type Details = { options: string; exe: string; startdir: string };

function appDetails(appid: number): Promise<Details> {
  return new Promise((resolve) => {
    let done = false;
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, (d: any) => {
      if (done) return;
      done = true;
      reg.unregister();
      resolve({
        options: d?.strLaunchOptions ?? "",
        exe: d?.strShortcutExe ?? "",
        startdir: d?.strShortcutStartDir ?? "",
      });
    });
    setTimeout(() => {
      if (!done) {
        done = true;
        reg.unregister();
        resolve({ options: "", exe: "", startdir: "" });
      }
    }, 3000);
  });
}

const hasSplash = (opts: string) => /\/[\w-]*wow-splash\/launch\.sh/.test(opts);

function withSplash(opts: string, launcher: string, appid: number): string {
  const rest = withoutSplash(opts);
  const wrapper = `"${launcher}" ${appid} %command%`;
  return rest.includes("%command%") ? rest.replace("%command%", wrapper) : `${wrapper} ${rest}`.trim();
}

function withoutSplash(opts: string): string {
  const rest = opts.replace(WRAPPER, "").trim();
  return rest === "%command%" ? "" : rest;
}

async function reportProblem(list: Shortcut[]) {
  const r = await bugReport();
  const enabled = list.filter((s) => hasSplash(s.options)).map((s) => `- ${s.name} (${s.appid}): \`${s.options}\``);
  const last = r.last_launch;
  const head = [
    "**What happened:**",
    "",
    "<!-- Describe what you saw, e.g. the splash stayed up, closed too early, flickered... -->",
    "",
    "**System**",
    `- WoW Splash ${r.plugin}, loader ${r.loader}`,
    `- ${r.os}`,
    `- xdotool: ${r.xdotool ? "yes" : "no"}, Deck controller: ${r.deck_controller ? "yes" : "no"}`,
    `- Settings: \`${JSON.stringify(r.settings)}\``,
    "",
    "**Shortcuts with the splash**",
    ...(enabled.length ? enabled : ["- none"]),
    "",
    "**Last launch**",
  ];
  let log: string[] = last?.log ?? [];
  const build = () =>
    [
      ...head,
      last
        ? `${last.time}, gaming mode: ${last.gaming_mode}, mode: ${last.mode}, result: ${last.result}\nmilestones: \`${JSON.stringify(last.reached)}\``
        : "No launch recorded yet.",
      ...(log.length ? ["```", ...log, "```"] : []),
    ].join("\n");
  const url = () =>
    `https://github.com/${REPO}/issues/new?title=${encodeURIComponent("Bug: ")}&body=${encodeURIComponent(build())}`;
  while (url().length > MAX_URL && log.length) log = log.slice(Math.ceil(log.length / 4));
  Navigation.CloseSideMenus();
  Navigation.NavigateToExternalWeb(url());
}

function ShortcutRow({ sc, info, onChange, named }: { sc: Shortcut; info: Info; onChange: () => void; named: boolean }) {
  const toggle = async (on: boolean) => {
    const opts = on ? withSplash(sc.options, info.launcher, sc.appid) : withoutSplash(sc.options);
    if (on) await setMode(sc.appid, "launch");
    SteamClient.Apps.SetAppLaunchOptions(sc.appid, opts);
    toaster.toast({ title: "WoW Splash", body: on ? "Splash on" : "Splash off" });
    setTimeout(onChange, 300);
  };

  return (
    <PanelSectionRow>
      <ToggleField
        label="Splash screen"
        description={named ? sc.name : undefined}
        checked={hasSplash(sc.options)}
        onChange={toggle}
      />
    </PanelSectionRow>
  );
}

function Content() {
  const [info, setInfo] = useState<Info | null>(null);
  const [list, setList] = useState<Shortcut[]>([]);

  const load = async () => {
    const i = await getInfo();
    // Move shortcuts still pointing at the old wrapper path to the new one.
    const sc = shortcuts();
    const details = await Promise.all(sc.map((s) => appDetails(s.appid)));
    const old = sc.filter((_, n) => OLD_PATH.test(details[n].options));
    for (const s of old) {
      const d = details[sc.indexOf(s)];
      d.options = withSplash(d.options, i.launcher, s.appid);
      SteamClient.Apps.SetAppLaunchOptions(s.appid, d.options);
    }
    if (old.length) {
      await new Promise((r) => setTimeout(r, 1000));
      const still = await Promise.all(old.map((s) => appDetails(s.appid)));
      if (!still.some((d) => OLD_PATH.test(d.options))) await dropOldLauncher();
    }
    // A shortcut counts as WoW if its program or Proton prefix holds WoW Forever / Battle.net.
    const all = sc.map((s, n) => ({ ...s, ...details[n] }));
    const wow = new Set(await wowShortcuts(all.map(({ appid, exe, startdir }) => ({ appid, exe, startdir }))));
    setInfo(i);
    setList(all.filter((s) => wow.has(s.appid)).map(({ appid, name, options }) => ({ appid, name, options })));
  };

  useEffect(() => {
    load();
  }, []);

  if (!info) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading…" />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      <PanelSection>
        {list.length === 0 && (
          <PanelSectionRow>
            <Field
              label="No WoW shortcut found"
              description="Add Battle.net to Steam as a non-Steam game and install WoW Forever in its Proton prefix."
            />
          </PanelSectionRow>
        )}
        {list.map((sc) => (
          <ShortcutRow key={sc.appid} sc={sc} info={info} onChange={load} named={list.length > 1} />
        ))}
      </PanelSection>
      <PanelSection title="Help">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="Or hold View + Menu on the Deck while it shows."
            onClick={async () => {
              const n = await closeSplash();
              toaster.toast({ title: "WoW Splash", body: n ? "Splash closed" : "No splash is showing" });
            }}
          >
            Close splash
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="Opens a GitHub issue with your system info and the last launch filled in."
            onClick={() => reportProblem(list)}
          >
            Report a problem
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "WoW Splash",
  titleView: <div className={staticClasses.Title}>WoW Splash</div>,
  content: <Content />,
  icon: <FaImage />,
  onDismount() {},
}));
