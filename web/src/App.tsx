import { Navigate, Route, Routes } from "react-router-dom";
import { ParkingLotPage } from "./ParkingLotPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ParkingLotPage captureMode="web" />} />
      <Route path="/truth" element={<ParkingLotPage captureMode="truth" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
