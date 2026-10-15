/** Phosphor 风格内联图标（256 网格，细线）；只含本项目用到的。 */
export const ICONS = {
  "arrow-right": '<path d="M40 128h176M144 56l72 72-72 72"/>',
  "arrow-left": '<path d="M216 128H40M112 56l-72 72 72 72"/>',
  download: '<path d="M128 40v112M80 104l48 48 48-48M40 168v40h176v-40"/>',
  copy: '<rect x="40" y="88" width="128" height="128" rx="6"/><path d="M88 88V40h128v128h-48"/>',
  printer: '<path d="M64 80V40h128v40"/><rect x="32" y="80" width="192" height="104" rx="6"/><path d="M64 152h128v72H64z"/>',
  pause: '<rect x="64" y="48" width="36" height="160" rx="6"/><rect x="156" y="48" width="36" height="160" rx="6"/>',
  x: '<path d="M196 60L60 196M196 196L60 60"/>',
  check: '<path d="M40 136l60 60L216 72"/>',
  warning: '<path d="M128 36L20 216h216z"/><path d="M128 100v52"/><circle class="f" cx="128" cy="184" r="10"/>',
  info: '<circle cx="128" cy="128" r="96"/><path d="M128 120v60"/><circle class="f" cx="128" cy="84" r="10"/>',
  question: '<circle cx="128" cy="128" r="96"/><path d="M100 102a28 28 0 1 1 40 25c-8 4-12 10-12 18v6"/><circle class="f" cx="128" cy="184" r="10"/>',
  search: '<circle cx="112" cy="112" r="72"/><path d="M163 163l57 57"/>',
  archive: '<rect x="32" y="48" width="192" height="48" rx="6"/><path d="M48 96v112h160V96M104 136h48"/>',
  "caret-down": '<path d="M208 96l-80 80-80-80"/>',
  "caret-right": '<path d="M96 48l80 80-80 80"/>',
  sun: '<circle cx="128" cy="128" r="52"/><path d="M128 24v20M128 212v20M24 128h20M212 128h20M54 54l14 14M188 188l14 14M54 202l14-14M188 68l14-14"/>',
  moon: '<path d="M216 152A92 92 0 0 1 104 40a92 92 0 1 0 112 112z"/>',
  monitor: '<rect x="32" y="48" width="192" height="136" rx="8"/><path d="M96 216h64M128 184v32"/>',
  gear: '<path d="M40 80h96M192 80h24M40 176h24M120 176h96"/><circle cx="164" cy="80" r="26"/><circle cx="92" cy="176" r="26"/>',
  out: '<path d="M216 100V40h-60M136 120l80-80M184 148v60H48V72h60"/>',
  merge: '<circle cx="72" cy="60" r="22"/><circle cx="72" cy="196" r="22"/><circle cx="188" cy="152" r="22"/><path d="M72 82v92M72 82c0 44 50 70 94 70"/>',
  prohibit: '<circle cx="128" cy="128" r="96"/><path d="M60 60l136 136"/>',
  dash: '<circle cx="128" cy="128" r="92" stroke-dasharray="26 22"/>',
  book: '<path d="M128 72c-24-20-56-24-96-24v152c40 0 72 4 96 24 24-20 56-24 96-24V48c-40 0-72 4-96 24zM128 72v152"/>',
  eye: '<path d="M128 56C56 56 20 128 20 128s36 72 108 72 108-72 108-72-36-72-108-72z"/><circle cx="128" cy="128" r="36"/>',
  plus: '<path d="M40 128h176M128 40v176"/>',
  sidebar: '<rect x="32" y="48" width="192" height="160" rx="8"/><path d="M96 48v160"/>',
  play: '<path d="M76 40l132 88-132 88z"/>',
  stop: '<rect x="56" y="56" width="144" height="144" rx="6"/>',
  send: '<path d="M224 32L32 104l80 32 32 80z"/><path d="M112 136l56-56"/>',
  pen: '<path d="M48 208l12-48L176 44l36 36L96 196zM152 68l36 36"/>',
  resume: '<path d="M80 104H32V56"/><path d="M66 190a96 96 0 1 0 0-124L32 104"/>',
  trash: '<path d="M40 64h176M96 64V40h64v24M200 64l-10 152H66L56 64M104 104v72M152 104v72"/>',
  clip: '<path d="M160 84l-80 80a20 20 0 0 0 28 28l96-96a40 40 0 0 0-56-56l-96 96a60 60 0 0 0 84 84l80-80"/>',
  dot: '<circle class="f" cx="128" cy="128" r="44"/>',
  minus: '<path d="M40 128h176"/>',
  bell: '<path d="M60 104a68 68 0 0 1 136 0c0 40 10 64 24 80H36c14-16 24-40 24-80zM100 208a28 28 0 0 0 56 0"/>',
} as const;

export type IconName = keyof typeof ICONS;

/** 给 HTML 字符串用（报告正文里的声明编号） */
export const iconHtml = (name: IconName) =>
  `<svg class="ic" viewBox="0 0 256 256" aria-hidden="true">${ICONS[name]}</svg>`;

export function Icon({ name, small = false }: { name: IconName; small?: boolean }) {
  return (
    <svg className={small ? "ic sm" : "ic"} viewBox="0 0 256 256" aria-hidden="true"
         dangerouslySetInnerHTML={{ __html: ICONS[name] }} />
  );
}
