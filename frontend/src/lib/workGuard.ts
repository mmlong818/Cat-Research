// Global work-in-progress guard for preventing accidental navigation
let _inProgress = false;

export function setWorkInProgress(v: boolean) {
  _inProgress = v;
}

export function guardNavigate(navigate: (to: string) => void, to: string) {
  if (_inProgress && !window.confirm("当前有工作进行中，确定离开此页面？")) return;
  navigate(to);
}
