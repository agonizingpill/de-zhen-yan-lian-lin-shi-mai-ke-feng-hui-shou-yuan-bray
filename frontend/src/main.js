import {login} from './login.js';
import {el} from './dom.js';
import {status} from './widgets.js';
import {ROLES, VENUES, session, setSession, setVenue, venue} from './store.js';
import {info, pages} from './pages/index.js';

const root = document.getElementById('app');
function venueSwitch() {
  const select = el('select',{'aria-label':'选择演练场地',name:'venue'},
    ...Object.entries(VENUES).map(([code,name]) =>
      el('option',{value:code,selected:code===venue()?'':undefined},code+' '+name)));
  select.addEventListener('change',() => { setVenue(select.value); render(); });
  return el('label',{class:'venue-switch'},el('span',{},'值守场地'),select);
}
function render() {
  if (!session()) {
    login(root, info, render);
    return;
  }
  const slug = location.hash.slice(1);
  const current = pages.find(page => page.key === slug) || pages[0];
  const workspace = el('main',{id:'workspace'});
  root.replaceChildren(el('header',{class:'top'},el('div',{class:'brand'},info.title),
    el('div',{class:'top-tools'},venueSwitch(),
      el('span',{},ROLES[session().role]),el('button',{class:'quiet',onclick:() => {
        setSession(null); render();
      }},'退出'))),
  el('div',{class:'shell'},el('nav',{'aria-label':'业务模块'},pages.map(page =>
    el('a',{href:'#'+page.key,'aria-current':page === current ? 'page' : undefined},page.title))),workspace));
  Promise.resolve(current.render(workspace,session().role)).catch(error => {
    if (workspace.isConnected) workspace.replaceChildren(status(error.message,'error'));
  });
}
window.addEventListener('hashchange',render);
render();
