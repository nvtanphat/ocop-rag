import leafLeft from "../assets/leaf-left.png";
import leafRight from "../assets/leaf-right.png";

export function Backdrop() {
  return (
    <div id="bgfx" aria-hidden="true">
      <div className="b-terr" />
      <div className="b-haze" />
      <div className="b-hero" />
      <img className="leaf l1" src={leafLeft} alt="" />
      <img className="leaf l2" src={leafRight} alt="" />
      <img className="leaf l3" src={leafRight} alt="" />
    </div>
  );
}
