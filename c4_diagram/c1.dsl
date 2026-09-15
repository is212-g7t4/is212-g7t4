workspace "ConnectSphere" "Event Planning and Venue Booking System" {

    model {
        // --- Actors ---
        eo = person "Event Organiser" "External client who submits and manages event requests." {
            tags "External Actor"
        }
        attendee = person "Attendee" "External user who registers for confirmed events." {
            tags "External Actor"
        }
        ec = person "Event Coordinator" "Internal staff who coordinates the event lifecycle." {
            tags "Internal Actor"
        }
        vs = person "Venue Staff" "Internal staff who manages spaces and approves bookings." {
            tags "Internal Actor"
        }
        ts = person "Technical Staff" "Internal staff who manages equipment requests." {
            tags "Internal Actor"
        }

        // --- External Systems ---
        email = softwareSystem "Notification Service" "External service for sending email/SMS alerts." {
            tags "External System" "Database"
        }
        supabase = softwareSystem "Supabase" "Stores user accounts and relational data for the backend." {
            tags "External System" "Database"
        }
        mongodb = softwareSystem "MongoDB Atlas" "Stores unstructured forum/communication records." {
            tags "External System" "Database"
        }

        // --- Core System (ConnectSphere) ---
        // Notice it is completely empty inside now!
        connectsphere = softwareSystem "ConnectSphere" "Event Planning and Venue Booking System." {
            tags "Internal System"
        }

        // --- High-Level Relationships ---
        // Actors connect directly to the main system
        eo -> connectsphere "Submits and manages event requests using" "HTTPS"
        attendee -> connectsphere "Registers for events using" "HTTPS"
        ec -> connectsphere "Manages planning & venue searches using" "HTTPS"
        vs -> connectsphere "Approves venue requests using" "HTTPS"
        ts -> connectsphere "Approves equipment requests using" "HTTPS"

        // Main system connects directly to the external systems
        connectsphere -> supabase "Authenticates users & reads/writes relational data in" "HTTPS/SQL"
        connectsphere -> mongodb "Reads/writes NoSQL communication entries in" "TCP"
        connectsphere -> email "Dispatches notifications using" "HTTPS"
    }

    views {
        // Generates Level 1
        systemContext connectsphere "SystemContext" {
            include *
            autoLayout tb
            description "Level 1: System Context Diagram for ConnectSphere."
        }

        // Styling (These styles auto-generate the Legend in Structurizr)
        styles {
            element "Internal Actor" {
                background #08427b
                color #ffffff
                shape Person
            }
            element "External Actor" {
                background #999999
                color #ffffff
                shape Person
            }
            element "Internal System" {
                background #1168bd
                color #ffffff
            }
            element "External System" {
                background #999999
                color #ffffff
            }
            element "Database" {
                shape Cylinder
            }
        }
    }
}