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
const setMode = callable<[appid: number, mode: Mode], Info["apps"]>("set_mode");
const closeSplash = callable<[], number>("close_splash");
const bugReport = callable<[], Record<string, any>>("bug_report");

// GitHub repo that "Report a problem" opens a new issue on.
const REPO = "AstroPhyzix/decky-wow-splash";
const MAX_URL = 7500; // GitHub rejects much longer new-issue links

declare const appStore: any;

const SHORTCUT = 1073741824; // app_type of non-Steam shortcuts
const LOOKS_LIKE_WOW = /warcraft|battle\.?net|\bwow\b/i;
// Our wrapper in launch options: "<...>/decky-wow-splash/launch.sh" <appid>
const WRAPPER = /"[^"]*\/decky-wow-splash\/launch\.sh"\s+\d+\s+/g;

function shortcuts(): { appid: number; name: string }[] {
  return (appStore?.allApps ?? [])
    .filter((a: any) => a.app_type === SHORTCUT)
    .map((a: any) => ({ appid: a.appid, name: a.display_name }))
    .sort((a: any, b: any) => a.name.localeCompare(b.name));
}

function launchOptions(appid: number): Promise<string> {
  return new Promise((resolve) => {
    let done = false;
    const reg = SteamClient.Apps.RegisterForAppDetails(appid, (d: any) => {
      if (done) return;
      done = true;
      reg.unregister();
      resolve(d?.strLaunchOptions ?? "");
    });
    setTimeout(() => {
      if (!done) {
        done = true;
        reg.unregister();
        resolve("");
      }
    }, 3000);
  });
}

const hasSplash = (opts: string) => opts.includes("/decky-wow-splash/launch.sh");

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
    `- WoW Splash ${r.plugin}, Decky ${r.decky}`,
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

function ShortcutRow({ sc, info, onChange }: { sc: Shortcut; info: Info; onChange: () => void }) {
  const enabled = hasSplash(sc.options);
  const launch = (info.apps[String(sc.appid)]?.mode ?? "launch") === "launch";
  const toggle = (on: boolean) => {
    const opts = on ? withSplash(sc.options, info.launcher, sc.appid) : withoutSplash(sc.options);
    SteamClient.Apps.SetAppLaunchOptions(sc.appid, opts);
    toaster.toast({ title: "WoW Splash", body: `${on ? "On" : "Off"} for ${sc.name}` });
    setTimeout(onChange, 300);
  };

  return (
    <>
      <PanelSectionRow>
        <ToggleField label={sc.name} checked={enabled} onChange={toggle} />
      </PanelSectionRow>
      {enabled && (
        <PanelSectionRow>
          <ToggleField
            label="Launch WoW directly"
            description={
              launch
                ? "Starts Battle.net and WoW. The splash stays until the game window opens."
                : "Splash only: covers Battle.net while it loads and signs in, then you press Play."
            }
            checked={launch}
            onChange={(v) => setMode(sc.appid, v ? "launch" : "splash").then(onChange)}
          />
        </PanelSectionRow>
      )}
    </>
  );
}

function Content() {
  const [info, setInfo] = useState<Info | null>(null);
  const [list, setList] = useState<Shortcut[]>([]);
  const [showAll, setShowAll] = useState(false);

  const load = async () => {
    const i = await getInfo();
    const all = shortcuts();
    const filtered = showAll ? all : all.filter((s) => LOOKS_LIKE_WOW.test(s.name));
    const withOpts = await Promise.all(
      filtered.map(async (s) => ({ ...s, options: await launchOptions(s.appid) })),
    );
    setInfo(i);
    setList(withOpts);
  };

  useEffect(() => {
    load();
  }, [showAll]);

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
      <PanelSection title="Show a splash for">
        {list.length === 0 && (
          <PanelSectionRow>
            <Field
              label="No WoW shortcut found"
              description="Add Battle.net or WoW to Steam as a non-Steam game, or show all shortcuts below."
            />
          </PanelSectionRow>
        )}
        {list.map((sc) => (
          <ShortcutRow key={sc.appid} sc={sc} info={info} onChange={load} />
        ))}
      </PanelSection>
      <PanelSection>
        <PanelSectionRow>
          <ToggleField label="Show all non-Steam shortcuts" checked={showAll} onChange={setShowAll} />
        </PanelSectionRow>
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
