import { ArrowUpRight } from "lucide-react";
import type { LandingFeature } from "./features";
import { ProductVisual } from "./ProductVisual";
export function FeatureSection({ feature, index }: { feature: LandingFeature; index: number }) {
 const Icon = feature.icon;
 return <section id={feature.id} data-feature={index} className={`landing-story-chapter ${["reports", "numbers", "assistant"].includes(feature.id) ? "landing-spotlight" : ""}`} aria-labelledby={`title-${feature.id}`}>
  <div className={`landing-feature landing-scroll-stage ${index % 2 ? "landing-feature-reverse" : ""}`}><div className="landing-story-step" aria-hidden="true"><span>THE WORKSPACE / {String(index + 1).padStart(2, "0")}</span><span>SCROLL TO EXPLORE</span><i><b /></i></div>
  <div className="landing-feature-copy"><p className="landing-kicker"><Icon size={18} aria-hidden="true" /> {String(index+1).padStart(2,"0")} / {feature.label}</p><h2 id={`title-${feature.id}`}>{feature.title}</h2><p>{feature.description}</p><a href="/app" className="landing-text-link">Explore in the app <ArrowUpRight size={15} /></a></div>
  {index % 3 === 0 ? <ProductVisual title={feature.label} items={feature.details} /> : <div className={`landing-feature-plate landing-plate-${index % 3}`}><span className="landing-plate-icon"><Icon size={46} strokeWidth={1.25} aria-hidden="true" /></span><p className="landing-plate-caption">{feature.label}</p><ul>{feature.details.map((detail,i)=><li key={detail}><span>0{i+1}</span>{detail}</li>)}</ul><span className="landing-plate-stamp" aria-hidden="true">EVIDENCE, ORGANIZED.</span></div>}
 </div></section>;
}
