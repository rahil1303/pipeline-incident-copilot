with enriched as (
    select * from {{ ref('int_tracks_enriched') }}
),

artist_stats as (
    select
        artist_names,
        count(*)                                        as total_tracks,
        round(avg(popularity)::numeric, 1)              as avg_popularity,
        max(popularity)                                 as peak_popularity,
        round(avg(danceability)::numeric, 3)            as avg_danceability,
        round(avg(energy)::numeric, 3)                  as avg_energy,
        round(avg(valence)::numeric, 3)                 as avg_valence,
        count(case when is_explicit then 1 end)         as explicit_track_count,
        round(avg(duration_minutes)::numeric, 2)        as avg_track_duration_minutes
    from enriched
    group by 1
)

select * from artist_stats
order by avg_popularity desc
