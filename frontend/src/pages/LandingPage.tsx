import { FindingsLogo } from "../components/FindingsLogo";
import { ThemeControl } from "../components/ThemeControl";
import { LandingLogin } from "../landing/LandingLogin";
import { LandingWorkflow } from "../landing/LandingWorkflow";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { useTheme } from "../theme";
import { features } from "../landing/features";
import { LandingHero } from "../landing/LandingHero";
import { FeatureSection } from "../landing/FeatureSection";
import { LandingCompanion } from "../landing/LandingCompanion";
import "../landing/landing.css";
export default function LandingPage() {
 const root=useRef<HTMLDivElement>(null); const progress=useRef<HTMLDivElement>(null); const [section,setSection]=useState(-1); const {theme,setTheme}=useTheme();
 useEffect(()=>{
  const previous=document.title; document.title="FindingsAI | AI research agent for evidence-led reports";
  const observer=new IntersectionObserver(entries=>{ entries.forEach(entry=>{ if(entry.isIntersecting){entry.target.classList.add("is-visible");} }); },{threshold:.15});
  root.current?.querySelectorAll(".landing-reveal").forEach(el=>observer.observe(el));root.current?.classList.add("landing-motion-ready");
  let frame=0;const update=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{ const maximum=document.documentElement.scrollHeight-window.innerHeight; if(progress.current)progress.current.style.transform=`scaleX(${maximum>0?window.scrollY/maximum:0})`;root.current?.querySelectorAll<HTMLElement>(".landing-story-chapter").forEach(el=>{ const rect=el.getBoundingClientRect(); const arrival=Math.max(0,Math.min(1,(window.innerHeight-rect.top)/(window.innerHeight*.8))); const travel=Math.max(0,Math.min(1,-rect.top/Math.max(1,rect.height-window.innerHeight))); el.style.setProperty("--story-arrival",String(arrival)); el.style.setProperty("--story-travel",String(travel)); }); if(window.scrollY<250)setSection(-1); else { const current=[...(root.current?.querySelectorAll<HTMLElement>("[data-feature]") || [])].find(el=>{const rect=el.getBoundingClientRect();return rect.top<=window.innerHeight*.15 && rect.bottom>window.innerHeight*.15;}); if(current)setSection(Number(current.dataset.feature)); } });};window.addEventListener("scroll",update,{passive:true});window.addEventListener("resize",update);update();
  return ()=>{observer.disconnect();cancelAnimationFrame(frame);window.removeEventListener("scroll",update);window.removeEventListener("resize",update);document.title=previous;};
 },[]);
 return <div className="landing" ref={root}><a className="landing-skip" href="#landing-main">Skip to content</a><div ref={progress} className="landing-scroll-progress" aria-hidden="true" />
 <header className="landing-nav"><a href="/landing" className="landing-brand"><FindingsLogo size={24} /></a><nav aria-label="Landing navigation"><a href="#features">Features</a><a href="#assistant">Assistant</a><a href="#start">Get started</a></nav><div className="landing-nav-actions"><ThemeControl theme={theme} onChange={setTheme} compact /><LandingLogin /><a href="/app" className="landing-nav-cta">Open app <ArrowUpRight size={15} /></a></div></header>
 <main id="landing-main"><LandingHero /><LandingWorkflow /><section id="features" className="landing-intro landing-reveal"><p className="landing-kicker">THE WORKSPACE, INSIDE OUT</p><h2>Not just an answer.<br />A way to understand it.</h2><p>From the first question to the next conversation, keep the sources, the reasoning, and the unanswered questions within reach.</p><div className="landing-feature-directory">{features.map(feature=><a href={`#${feature.id}`} key={feature.id}>{feature.label}</a>)}</div></section>
 <div className="landing-feature-list">{features.map((feature,index)=><FeatureSection key={feature.id} feature={feature} index={index} />)}</div>
 <section id="start" className="landing-final landing-reveal"><p className="landing-kicker">YOUR NEXT QUESTION STARTS HERE</p><h2>Make room for<br /><em>a better question.</em></h2><p>Bring your curiosity. Follow the evidence. Keep learning.</p><a href="/app" className="landing-primary">Open your research workspace <ArrowUpRight size={18} /></a></section></main>
 <footer className="landing-footer"><a href="/landing" className="landing-brand"><FindingsLogo size={22} /></a><p>Evidence, organized. Curiosity, encouraged.</p><nav aria-label="Footer navigation"><a href="#features">Features</a><a href="#pdf">PDF research</a><a href="/app">Open app</a><a href="#landing-main">Back to top</a></nav></footer>
 <LandingCompanion section={section<0?"Curiosity looks good on you.":features[section]?.label || "Keep exploring."} expression={section<0?0:section} />
 </div>;
}
