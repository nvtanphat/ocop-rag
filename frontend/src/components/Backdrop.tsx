import leafLeft from "../assets/leaf-left.png";
import leafRight from "../assets/leaf-right.png";

export function Backdrop() {
  return (
    <div className="landscape" aria-hidden="true">
      <div className="landscape-terrain" />
      <div className="landscape-haze" />
      <div className="landscape-hero" />
      <img className="landscape-leaf leaf-top" src={leafLeft} alt="" />
      <img className="landscape-leaf leaf-bottom" src={leafRight} alt="" />
      <img className="landscape-leaf leaf-right" src={leafRight} alt="" />
    </div>
  );
}
