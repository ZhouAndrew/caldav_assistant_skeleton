"use strict";
// Native DOM effect boundary only: policy and Start execution remain in background.
(() => {
  const win=globalThis, bridge=win.__caldavAssistantStartBridge;
  if (!bridge || win.__caldavAssistantStartUI) return;
  const id="caldav-assistant-task-start";
  let button=null, renderedSelection=[], lastSelection=null, disposed=false;
  function selectedRefs() {
    const tree=document.getElementById("calendar-task-tree");
    if(!tree?.mTreeView) return [];
    return Array.from(tree.selectedTasks || []).map(task=>({
      calendarId:String(task.calendar?.superCalendar?.id || task.calendar?.id || ""),
      id:String(task.id || ""),recurrenceId:String(task.recurrenceId?.icalString || "")
    }));
  }
  function command() {
    const snapshot=renderedSelection.map(ref=>({...ref}));
    button.disabled=true;
    bridge.start(snapshot);
  }
  function ensureButton() {
    const toolbar=document.getElementById("task-actions-toolbar");
    const completed=document.getElementById("task-actions-markcompleted");
    if (!toolbar || !completed?.parentNode || !toolbar.contains(completed)) return false;
    if (button && !toolbar.contains(button)) {button.removeEventListener("command",command);button.remove();button=null;lastSelection=null;}
    if (!button) {
      button=document.createXULElement("toolbarbutton");button.id=id;
      button.setAttribute("label","Start");button.setAttribute("tooltiptext","Start the selected Task");
      button.setAttribute("class","toolbarbutton-1 message-header-view-button");
      button.setAttribute("tabindex","0");button.disabled=true;
      button.addEventListener("command",command);
      completed.parentNode.insertBefore(button,completed.nextSibling);
      lastSelection=null;
    }
    return true;
  }
  function refresh(force=false) {
    if (disposed || !ensureButton()) return;
    const refs=selectedRefs(), fingerprint=JSON.stringify(refs);
    if (force || fingerprint!==lastSelection) {
      lastSelection=fingerprint;button.disabled=true;
      bridge.selectionChanged(refs);
    }
  }
  const selectionChanged=()=>refresh();
  document.addEventListener("select",selectionChanged,true);
  const observer=new MutationObserver(()=>refresh());
  observer.observe(document.documentElement,{childList:true,subtree:true});
  const timer=setInterval(()=>refresh(),250);
  win.__caldavAssistantStartUI={
    refresh:()=>refresh(true),
    update(enabled,refs) {
      if (disposed || !ensureButton()) return;
      // Discard a delayed render for a selection no longer visible in this window.
      if (JSON.stringify(selectedRefs())!==JSON.stringify(refs)) {refresh(true);return;}
      renderedSelection=refs.map(ref=>({...ref}));button.setAttribute("data-task-id",refs.length===1?refs[0].id:"");button.disabled=!enabled;
    },
    cleanup() {
      disposed=true;clearInterval(timer);observer.disconnect();
      document.removeEventListener("select",selectionChanged,true);
      if(button){button.removeEventListener("command",command);button.remove();}
      delete win.__caldavAssistantStartUI;
    }
  };
  refresh(true);
})();
