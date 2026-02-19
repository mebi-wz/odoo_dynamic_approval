CREATE OR REPLACE VIEW dashboard_approval_request AS (
    SELECT
        MIN(id) AS id,
        res_model,
        module_name,
        status,
        COUNT(*) AS count
    FROM approval_request
    GROUP BY module_name,res_model, status
);
