/*
 * ConnectSphere — C2 Container diagram (Structurizr DSL)
 *
 * One Front-End App, one API Application wrapping every backend service,
 * and the two cloud-hosted databases kept OUTSIDE the system boundary
 * (external systems, not containers) — Supabase and MongoDB Atlas.
 * Actors use the same person shape/tags as the C1 diagram on the Miro
 * board (https://miro.com/app/board/uXjVHqeuVHs=/).
 */

workspace "ConnectSphere" "C2 — Containers" {

    !identifiers hierarchical

    model {

        // --- Actors ---
        eo = person "Event Organiser" "External client who submits and manages event requests." {
            tags "External"
        }
        attendee = person "Attendee" "External user who registers for confirmed events." {
            tags "External"
        }
        ec = person "Event Coordinator" "Internal staff who coordinates the event lifecycle." {
            tags "Internal"
        }
        vs = person "Venue Staff" "Internal staff who manages spaces and approves bookings." {
            tags "Internal"
        }
        ts = person "Technical Staff" "Internal staff who manages equipment requests." {
            tags "Internal"
        }

        # ---- External systems — cloud-hosted, kept outside the system boundary ----
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." "External System"
        mongodb  = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." "External System"
        emailProvider = softwareSystem "Notification Service" "External service for sending email/SMS alerts." "External System"

        # ---- ConnectSphere system boundary ----
        connectSphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." "ConnectSphere System" {

            frontEndApp = container "Front-End App" "GUI for submitting, reviewing, and managing events, bookings, and registrations." "React, TypeScript, Vite" "Web Application"

            apiApplication = container "API Application" "Backend REST API handling event, venue, equipment, and registration business logic." "Python, Flask" "Backend Application"
        }

        # ================= Relationships =================

        eo       -> connectSphere.frontEndApp "Submits and manages event requests using" "HTTPS"
        attendee -> connectSphere.frontEndApp "Registers for events using" "HTTPS"
        ec       -> connectSphere.frontEndApp "Manages planning & venue searches using" "HTTPS"
        vs       -> connectSphere.frontEndApp "Approves venue requests using" "HTTPS"
        ts       -> connectSphere.frontEndApp "Approves equipment requests using" "HTTPS"

        connectSphere.frontEndApp -> connectSphere.apiApplication "Makes API calls to" "HTTPS/JSON"

        connectSphere.apiApplication -> supabase "Authenticates users & reads/writes relational data in" "HTTPS/SQL"
        connectSphere.apiApplication -> mongodb "Reads/writes NoSQL communication entries in" "TCP"
        connectSphere.apiApplication -> emailProvider "Dispatches notifications using" "HTTPS"
    }

    views {

        container connectSphere "C2-Containers" {
            include *
            autoLayout lr
            title "ConnectSphere — Containers (C2)"
        }

        styles {
            element "Person" {
                shape person
                fontSize 22
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Internal" {
                background #0b3d6e
                color #ffffff
            }
            element "External System" {
                background #999999
                color #ffffff
                shape cylinder
            }
            element "ConnectSphere System" {
                background #ffffff
                color #1a1a1a
            }
            element "Web Application" {
                background #305bab
                color #ffffff
                shape webBrowser
            }
            element "Backend Application" {
                background #438dd5
                color #ffffff
            }
            relationship "Relationship" {
                routing Orthogonal
            }
        }
    }
}
