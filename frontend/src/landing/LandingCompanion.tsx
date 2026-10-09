import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
export function LandingCompanion({ section, expression }: { section: string; expression: number }) {
 const [dismissed,setDismissed]=useState(false);
 const face=useRef<SVGGElement>(null);
 useEffect(()=>{
  const media=window.matchMedia("(prefers-reduced-motion: reduce)"); let frame=0;
  const follow=(event:PointerEvent)=>{ if(media.matches)return; cancelAnimationFrame(frame); frame=requestAnimationFrame(()=>{ if(face.current)face.current.style.transform=`translate(${(event.clientX/window.innerWidth-.5)*7}px, ${(event.clientY/window.innerHeight-.5)*5}px)`; }); };
  const reset=()=>{ if(face.current)face.current.style.transform="none"; };
  window.addEventListener("pointermove",follow,{passive:true}); media.addEventListener("change",reset);
  return ()=>{ cancelAnimationFrame(frame);window.removeEventListener("pointermove",follow);media.removeEventListener("change",reset); };
 },[]);
 if(dismissed)return null;
 return <aside className="landing-companion" aria-label="Landing page companion" data-expression={expression%3}><button onClick={()=>setDismissed(true)} aria-label="Dismiss companion"><X size={14} /></button><svg viewBox="0 0 80 80" aria-hidden="true"><g className="landing-orb"><path d="M17 29Q10 5 30 17Q40 12 50 17Q70 5 63 29Q77 62 53 69H27Q3 62 17 29Z" fill="currentColor" /><g ref={face}><ellipse cx="30" cy="36" rx="5" ry="7" /><ellipse cx="50" cy="36" rx="5" ry="7" /><path className="landing-orb-smile" d="M34 49Q40 56 46 49" fill="none" strokeWidth="3" strokeLinecap="round" /></g></g></svg><p>{section}</p></aside>;
}
