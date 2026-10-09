import { ArrowUpRight, Check, Circle, Quote, Search } from "lucide-react";
export function ProductVisual({ title = "From question to evidence.", items = ["A focused research question", "Sources with traceable excerpts", "A report that keeps uncertainty visible"], hero = false }: { title?: string; items?: string[]; hero?: boolean }) {
  const Heading = hero ? "h2" : "h3";
  return <div className={`landing-product ${hero ? "landing-product-hero" : ""}`}>
    <div className="landing-product-toolbar"><span className="landing-window-dots" aria-hidden="true"><Circle /><Circle /><Circle /></span><span>FindingsAI · product illustration</span><ArrowUpRight size={15} aria-hidden="true" /></div>
    <div className="landing-product-content"><div className="landing-demo-label"><Search size={15} aria-hidden="true" /> AN EVIDENCE-LED WORKSPACE</div><Heading>{title}</Heading>
      <div className="landing-demo-flow" aria-hidden="true"><span>Question</span><i /><span>Evidence</span><i /><span>Report</span></div>
      <ul>{items.map((item,index)=><li key={item}><span className="landing-demo-check"><Check size={15} aria-hidden="true" /></span><span>{item}</span><span className="landing-demo-index">0{index+1}</span></li>)}</ul>
      <div className="landing-demo-note"><Quote size={17} aria-hidden="true" /><p>Follow the source. Keep the context.<br /><span>Illustrative interface, not a research result.</span></p></div>
    </div>
  </div>;
}
