-- gBOAR Database Initialization Script
-- Create the database
CREATE DATABASE "gBOAR";

-- Connect to it
\c "gBOAR"

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. edge_device
CREATE TABLE
    edge_device (
        edge_id VARCHAR PRIMARY KEY,
        name VARCHAR,
        location TEXT
    );

-- 2. camera
CREATE TABLE
    camera (
        camera_id VARCHAR PRIMARY KEY,
        edge_id VARCHAR REFERENCES edge_device (edge_id),
        type VARCHAR,
        location_coordinates POINT,
        technical_params_json JSONB,
        elevation NUMERIC,
        status VARCHAR,
        temperature NUMERIC,
        battery_level INTEGER CHECK (battery_level BETWEEN 0 AND 100)
    );

-- 3. dataset_store
CREATE TABLE
    dataset_store (
        event_id VARCHAR PRIMARY KEY,
        camera_id VARCHAR REFERENCES camera (camera_id),
        time TIMESTAMPTZ,
        count INTEGER,
        image_path TEXT,
        event_coordinates POINT
    );

-- 4. animal_detected
CREATE TABLE
    animal_detected (
        detection_id_uuid UUID PRIMARY KEY DEFAULT uuid_generate_v4 (),
        event_id VARCHAR REFERENCES dataset_store (event_id),
        animal_type VARCHAR,
        distance NUMERIC,
        size_estimate NUMERIC,
        confidence NUMERIC CHECK (confidence BETWEEN 0.0 AND 1.0)
    );