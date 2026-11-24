import {venue} from './store.js';

export const patchNames={live:'通路接入',isolated:'单点隔离',restored:'备用路复位'};
export const labels={local:'单点邻域异常',coordinated:'同期同频协作',normal:'正常'};
export const channels=['BUS-A','BUS-B','BUS-C'];
export const purpose={live:'主路试听',reline:'复线试音'};
export const feature={peak_share:'峰值频率占比',ring_index:'持续回响指数',level:'整体声级',self_echo:'自身回路关联'};

// 草稿按场隔离：切换场地后各页只记住本场选中的窗口、发现与隔离单。
const deskByVenue = {};
function current() {
  const code = venue();
  if (!deskByVenue[code]) deskByVenue[code] = {finding:null,window:null,ticket:null};
  return deskByVenue[code];
}
export const desk = new Proxy({}, {
  get(_target, key) { return current()[key]; },
  set(_target, key, value) { current()[key] = value; return true; }
});
