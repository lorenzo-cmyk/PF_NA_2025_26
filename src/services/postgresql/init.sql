-- WatchEdge Database Initialization Script

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- ENUM for camera status
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'camera_status') THEN
    CREATE TYPE camera_status AS ENUM ('Online', 'Offline');
  END IF;
END$$;

-- 1. edge_device: top-level entity representing a physical edge computing node
CREATE TABLE IF NOT EXISTS edge_device (
  edge_id              UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
  name                 TEXT          NOT NULL,
  location             TEXT
);

-- 2. camera: imaging hardware, child of edge_device
CREATE TABLE IF NOT EXISTS camera (
  camera_id            UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
  edge_id              UUID          NOT NULL REFERENCES edge_device(edge_id) ON DELETE RESTRICT,
  type                 TEXT,
  location_coordinates GEOGRAPHY(Point, 4326),
  technical_params_json JSONB        DEFAULT '{}'::jsonb,
  elevation            DECIMAL(8,2),
  status               camera_status NOT NULL DEFAULT 'Offline',
  temperature          DECIMAL(5,2),
  battery_level        DECIMAL(5,2)  CHECK (battery_level BETWEEN 0 AND 100)
);

-- 3. datasetstore: one row per captured image/event, child of camera
CREATE TABLE IF NOT EXISTS datasetstore (
  event_id             UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
  camera_id            UUID          NOT NULL REFERENCES camera(camera_id) ON DELETE CASCADE,
  time                 TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  count                INT           NOT NULL DEFAULT 0,
  imagepath            TEXT          NOT NULL
);

-- 4. animaldetected: AI detection result, child of datasetstore
CREATE TABLE IF NOT EXISTS animaldetected (
  detection_id         UUID          PRIMARY KEY DEFAULT uuid_generate_v4(),
  event_id             UUID          NOT NULL REFERENCES datasetstore(event_id) ON DELETE CASCADE,
  animal_type          TEXT,
  distance             DECIMAL(6,2),
  size_estimate        DECIMAL(6,2),
  confidence           DECIMAL(4,3)  CHECK (confidence BETWEEN 0 AND 1)
);

-- Indexes for faster joins
CREATE INDEX IF NOT EXISTS idx_datasetstore_camera  ON datasetstore(camera_id);
CREATE INDEX IF NOT EXISTS idx_animaldetected_event ON animaldetected(event_id);

-- Trigger: keep datasetstore.count in sync with animaldetected row count
CREATE OR REPLACE FUNCTION refresh_event_count()
  RETURNS TRIGGER AS $$
DECLARE
  target_event_id UUID;
BEGIN
  IF TG_OP = 'DELETE' THEN
    target_event_id := OLD.event_id;
  ELSE
    target_event_id := NEW.event_id;
  END IF;

  UPDATE datasetstore
    SET count = (
      SELECT COUNT(*) FROM animaldetected
       WHERE event_id = target_event_id
    )
  WHERE event_id = target_event_id;

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_refresh_count ON animaldetected;
CREATE TRIGGER trg_refresh_count
  AFTER INSERT OR DELETE ON animaldetected
  FOR EACH ROW EXECUTE FUNCTION refresh_event_count();