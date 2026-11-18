"""
Build the travel planner graph.

    from travel_agent.graph import build_graph
    graph = build_graph()
    result = graph.invoke({"user_query": "plan me a 5 days trip", "messages": [], "llm_calls": 0},
                          config={"configurable": {"thread_id": "t1"}})
    print(result["itinerary"])
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import TravelState


def build_graph(checkpointer=None):
    b = StateGraph(TravelState)

    b.add_node("extract_trip", nodes.extract_trip)
    b.add_node("suggest_destination", nodes.suggest_destination)
    b.add_node("plan_country", nodes.plan_country)
    b.add_node("prepare_search", nodes.prepare_search)
    b.add_node("search_flight", nodes.search_flight)
    b.add_node("search_hotel", nodes.search_hotel)
    b.add_node("build_itinerary", nodes.build_itinerary)

    b.add_edge(START, "extract_trip")
    b.add_conditional_edges("extract_trip", nodes.route_destination)
    b.add_edge("suggest_destination", "prepare_search")
    b.add_edge("plan_country", "prepare_search")
    b.add_edge("prepare_search", "search_flight")
    b.add_edge("prepare_search", "search_hotel")
    b.add_edge(["search_flight", "search_hotel"], "build_itinerary")
    b.add_edge("build_itinerary", END)

    return b.compile(checkpointer=checkpointer or MemorySaver())
